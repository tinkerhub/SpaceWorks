from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.boxes.access import makerspace_for_action, qr_for_action
from apps.boxes.qr_admission import admitted_qr, create_tool_qr, require_qr_request_scope
from apps.boxes.api_views_eligibility import _allowed_scanner_actions
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.boxes.qr_render import render_qr_label_svg
from apps.boxes.serializers import (
    BoxSerializer,
    CreateBoxQrSerializer,
    CreateToolQrSerializer,
    QrCodeSerializer,
    QrRebindResultSerializer,
    QrRebindTargetSerializer,
    QrResolveResultSerializer,
    QrResolveSerializer,
    QrScanResultSerializer,
    QrScanSerializer,
    qr_target_payload,
)
from apps.boxes.rebind import preflight_rebind, rebind_qr_target
from apps.boxes.services import create_box_with_qr, revoke_qr_code
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.guards import require_module
from apps.openapi import (
    QR_BOX_EXAMPLE,
    QR_RESOLVE_REQUEST_EXAMPLE,
    QR_RESOLVE_RESPONSE_EXAMPLE,
    QR_SCAN_EXAMPLE,
)


# On a tenant's own domain the target makerspace comes from the body `makerspace_id`
# (create routes) or the payload's QR row (scan/resolve); an invalid origin hint
# receives 403 before lookup. An admitted QR with a missing/foreign target gets 404.
QR_ORIGIN_ERRORS = {
    400: OpenApiResponse(description="Invalid request or required module is disabled."),
    403: OpenApiResponse(description="Permission denied, or the target is outside this site's makerspace."),
    404: OpenApiResponse(description="QR or target not found in the caller's makerspace scope."),
}
QR_WRITE_ERRORS = {
    **QR_ORIGIN_ERRORS,
    423: OpenApiResponse(ErrorSerializer, description="tenant_migration_quiesced: tenant writes are frozen for migration."),
    503: OpenApiResponse(ErrorSerializer, description="tenant_migration_gate_unavailable: the source gate could not prove the write is safe."),
}


class QrPermissionMixin:
    permission_classes = [IsActiveStaff]

    def _require_qr(self, user, makerspace_id):
        require_module(makerspace_id, "qr_management")
        if (
            user.access_status != User.AccessStatus.ACTIVE
            or not rbac.can(user, rbac.Action.MANAGE_QR, makerspace_id)
        ):
            raise PermissionDenied()


class CreateBoxQrView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Create a QR-coded box",
        request=CreateBoxQrSerializer,
        responses={201: BoxSerializer, **QR_WRITE_ERRORS},
        examples=[QR_BOX_EXAMPLE],
    )
    def post(self, request, *args, **kwargs):
        serializer = CreateBoxQrSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        makerspace = makerspace_for_action(request.user, rbac.Action.MANAGE_QR, data["makerspace_id"])
        self._require_qr(request.user, makerspace.id)
        parent = None
        if data.get("parent_id"):
            parent = get_object_or_404(Box, pk=data["parent_id"], makerspace=makerspace)
        box = create_box_with_qr(request.user, Box(
            makerspace=makerspace,
            parent=parent,
            label=data["label"],
            location=data.get("location", ""),
            description=data.get("description", ""),
        ))
        return Response(BoxSerializer(box).data, status=status.HTTP_201_CREATED)


class CreateToolQrView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Create or reuse a QR code for a product or asset",
        request=CreateToolQrSerializer,
        responses={201: QrCodeSerializer, **QR_WRITE_ERRORS},
    )
    def post(self, request, *args, **kwargs):
        serializer = CreateToolQrSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        makerspace = makerspace_for_action(request.user, rbac.Action.MANAGE_QR, data["makerspace_id"])
        self._require_qr(request.user, makerspace.id)
        if data.get("asset_id"):
            target = get_object_or_404(InventoryAsset, pk=data["asset_id"], makerspace=makerspace)
            target_type = QrCode.TargetType.ASSET
        else:
            target = get_object_or_404(InventoryProduct, pk=data["product_id"], makerspace=makerspace)
            if target.tracking_mode == TrackingMode.INDIVIDUAL:
                raise ValidationError("Individual-tracked inventory requires unit QR codes.")
            target_type = QrCode.TargetType.PRODUCT
        require_qr_request_scope(request, [makerspace.id])
        qr = create_tool_qr(request.user, makerspace.id, target, target_type)
        return Response(QrCodeSerializer(qr).data, status=status.HTTP_201_CREATED)


class QrScanView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Record a QR scan",
        description="Context is issue, return or inventory_check; scan events are immutable.",
        request=QrScanSerializer,
        responses={201: QrScanResultSerializer, **QR_WRITE_ERRORS},
        examples=[QR_SCAN_EXAMPLE],
    )
    def post(self, request, *args, **kwargs):
        serializer = QrScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        qr = qr_for_action(request.user, rbac.Action.MANAGE_QR, payload=data["payload"], status=QrCode.Status.ACTIVE)
        self._require_qr(request.user, qr.makerspace_id)
        require_qr_request_scope(request, [qr.makerspace_id])
        qr_target_payload(qr)  # Unlocked target ownership preflight.
        _validate_scan_request(data.get("request_id"), qr)
        with admitted_qr(request.user, qr, rbac.Action.MANAGE_QR, "qr_management") as (actor, qr):
            require_qr_request_scope(request, [qr.makerspace_id])
            target_payload = qr_target_payload(qr)
            request_id = data.get("request_id")
            _validate_scan_request(request_id, qr)
            scan = QrScanEvent.objects.create(
                makerspace=qr.makerspace,
                qr_code=qr,
                actor=actor,
                context=data["context"],
                request_id=request_id,
            )
            audit.record(
                actor,
                "qr.scanned",
                makerspace=qr.makerspace,
                target=qr,
                meta={"context": scan.context, "scan_id": scan.id},
            )
        return Response(
            {
                "qr": QrCodeSerializer(qr).data,
                "target": target_payload,
                "scan_id": scan.id,
            },
            status=status.HTTP_201_CREATED,
        )


class QrResolveView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Resolve QR target and scanner allowed actions",
        description=(
            "Resolve the opaque payload encoded in a physical QR label to its target "
            "(box, product, or asset) and the scanner actions the caller may take. "
            "`payload` is the raw 32-char lowercase hex token printed on the label "
            "(Python `uuid4().hex`, e.g. `3f9a1c2b4d5e6f7081920a1b2c3d4e5f`) - it is the "
            "value stored as `QrCode.payload` (and `Box.code` for boxes), not a URL or JSON. "
            "Resolving a QR also records an immutable scanner-lookup scan event."
        ),
        request=QrResolveSerializer,
        responses={200: QrResolveResultSerializer, **QR_WRITE_ERRORS},
        examples=[QR_RESOLVE_REQUEST_EXAMPLE, QR_RESOLVE_RESPONSE_EXAMPLE],
    )
    def post(self, request, *args, **kwargs):
        serializer = QrResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        qr = qr_for_action(request.user, rbac.Action.VIEW_INVENTORY, payload=serializer.validated_data["payload"], status=QrCode.Status.ACTIVE)
        require_module(qr.makerspace, "scanner")
        require_qr_request_scope(request, [qr.makerspace_id])
        qr_target_payload(qr)  # Unlocked target ownership preflight.
        with admitted_qr(request.user, qr, rbac.Action.VIEW_INVENTORY, "scanner") as (actor, qr):
            require_qr_request_scope(request, [qr.makerspace_id])
            target_payload = qr_target_payload(qr)
            allowed_actions = _allowed_scanner_actions(actor, qr)
            scan = QrScanEvent.objects.create(
                makerspace=qr.makerspace,
                qr_code=qr,
                actor=actor,
                context=QrScanEvent.Context.SCANNER_LOOKUP,
            )
            audit.record(
                actor,
                "qr.scanned",
                makerspace=qr.makerspace,
                target=qr,
                meta={"context": scan.context, "scan_id": scan.id},
            )
        return Response(
            {
                "qr": QrCodeSerializer(qr).data,
                "target": target_payload,
                "allowed_actions": allowed_actions,
            }
        )


class QrPrintView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Render QR label SVG",
        responses={200: OpenApiResponse(description="QR payload, SVG label and target."), **QR_ORIGIN_ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        qr = qr_for_action(request.user, rbac.Action.MANAGE_QR, pk=pk)
        self._require_qr(request.user, qr.makerspace_id)
        target_payload = qr_target_payload(qr)
        return Response(
            {
                "payload": qr.payload,
                "svg": render_qr_label_svg(qr.payload),
                "target": target_payload,
            }
        )


class QrRevokeView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Revoke active QR code",
        request=None,
        responses={200: QrCodeSerializer, **QR_WRITE_ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        qr = qr_for_action(request.user, rbac.Action.MANAGE_QR, pk=pk)
        self._require_qr(request.user, qr.makerspace_id)
        require_qr_request_scope(request, [qr.makerspace_id])
        qr = revoke_qr_code(request.user, qr)
        return Response(QrCodeSerializer(qr).data)


class QrRebindTargetView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["QR assets"],
        summary=(
            "Rebind a saved QR to another product/asset "
            "(cross-makerspace = superadmin) and optionally rename"
        ),
        request=QrRebindTargetSerializer,
        responses={
            200: QrRebindResultSerializer,
            409: OpenApiResponse(description="Outstanding loan or target QR conflict."),
            **QR_WRITE_ERRORS,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        serializer = QrRebindTargetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        admission = preflight_rebind(request.user, pk, serializer.validated_data)
        require_qr_request_scope(request, admission[3])
        result = rebind_qr_target(request.user, pk, serializer.validated_data, admission=admission)
        return Response(
            {
                "qr": QrCodeSerializer(result.qr).data,
                "target": qr_target_payload(result.qr),
            }
        )


def _validate_scan_request(request_id, qr):
    if request_id is not None:
        from apps.hardware_requests.models import HardwareRequest

        # Immutable scan evidence must inherit the request's actual tenant too.
        if not HardwareRequest.objects.filter(pk=request_id, makerspace_id=qr.makerspace_id).exists():
            raise ValidationError({"request_id": "Request belongs to a different makerspace."})
