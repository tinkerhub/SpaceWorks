from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.boxes.models import QrCode
from apps.boxes.qr_admission import current_qr_actor, qr_write
from apps.boxes.serializers import QrCodeSerializer
from apps.boxes.targets import qr_target
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.guards import require_module, require_module_locked
from apps.makerspaces.models import Makerspace
from apps.operations import qr_zip, services
from apps.operations.models import QrPrintBatch
from apps.operations.serializers import (
    AssetGenerateResultSerializer,
    AssetGenerateSerializer,
    EmptySerializer,
    QrPrintBatchCreateSerializer,
    QrPrintBatchDetailSerializer,
    QrPrintBatchItemCreateSerializer,
    QrPrintBatchItemResultSerializer,
    QrPrintBatchSerializer,
)


BATCH_ERRORS = {
    400: OpenApiResponse(description="Invalid request, or the module is off for this makerspace."),
    403: OpenApiResponse(description="Permission denied."),
    404: OpenApiResponse(description="Not found in the caller's scope."),
}


@extend_schema_view(
    get=extend_schema(tags=["QR print batches"], summary="List QR print batches", request=None, responses={200: QrPrintBatchSerializer(many=True)}),
    post=extend_schema(tags=["QR print batches"], summary="Create QR print batch", request=QrPrintBatchCreateSerializer, responses={201: QrPrintBatchSerializer, **BATCH_ERRORS}),
)
class QrPrintBatchListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsActiveStaff]

    def get_serializer_class(self):
        return QrPrintBatchCreateSerializer if self.request.method == "POST" else QrPrintBatchSerializer

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "qr_print_batches")
        require_action(self.request.user, rbac.Action.MANAGE_QR, makerspace_id)
        return QrPrintBatch.objects.filter(makerspace_id=makerspace_id).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        makerspace = get_object_or_404(Makerspace, pk=self.kwargs["makerspace_id"])
        require_module(makerspace, "qr_print_batches")
        require_action(request.user, rbac.Action.MANAGE_QR, makerspace.id)
        serializer = QrPrintBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            require_module_locked(makerspace.id, "qr_print_batches")
            batch = QrPrintBatch.objects.create(makerspace=makerspace, title=serializer.validated_data["title"], created_by=request.user)
            audit.record(request.user, "qr_print_batch.created", makerspace=makerspace, target=batch)
        return Response(QrPrintBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(tags=["QR print batches"], summary="Retrieve QR print batch", request=None, responses={200: QrPrintBatchDetailSerializer}),
)
class QrPrintBatchDetailView(generics.RetrieveAPIView):
    serializer_class = QrPrintBatchDetailSerializer
    permission_classes = [IsActiveStaff]

    def get_queryset(self):
        return rbac.scope_by_action(self.request.user, rbac.Action.MANAGE_QR, QrPrintBatch.objects.prefetch_related("items__qr_code"))

    def get_object(self):
        batch = super().get_object()
        require_module(batch.makerspace, "qr_print_batches")
        return batch


class QrPrintBatchItemView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = QrPrintBatchItemCreateSerializer

    @extend_schema(tags=["QR print batches"], summary="Add QR code to print batch", request=QrPrintBatchItemCreateSerializer, responses={201: QrPrintBatchItemResultSerializer, **BATCH_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        batch = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, QrPrintBatch.objects.all()), pk=pk)
        require_module(batch.makerspace, "qr_print_batches")
        serializer = QrPrintBatchItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        qr = get_object_or_404(QrCode, pk=serializer.validated_data["qr_code_id"], makerspace=batch.makerspace)
        qr_target(qr)
        if qr.target_type not in {QrCode.TargetType.PRODUCT, QrCode.TargetType.ASSET}:
            raise ValidationError("QR print batches only accept inventory item or unit QR codes.")
        with transaction.atomic():
            require_module_locked(batch.makerspace_id, "qr_print_batches", no_key=True)
            item = services.add_qr_to_batch(
                request.user,
                batch,
                qr,
                serializer.validated_data.get("label_text", ""),
                serializer.validated_data.get("sort_order"),
            )
        return Response({"id": item.id}, status=status.HTTP_201_CREATED)


class QrPrintBatchDownloadView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = EmptySerializer

    @extend_schema(
        tags=["QR print batches"],
        summary="Download QR print batch as a ZIP of captioned SVGs",
        request=None,
        responses={(200, "application/zip"): OpenApiTypes.BINARY, **BATCH_ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        batch = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, QrPrintBatch.objects.prefetch_related("items__qr_code")), pk=pk)
        require_module(batch.makerspace, "qr_print_batches")
        data = qr_zip.build_batch_zip(batch)
        response = HttpResponse(data, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="qr-batch-{batch.id}.zip"'
        return response


class AssetGenerateView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = AssetGenerateSerializer

    @extend_schema(
        tags=["Asset units"],
        summary="Generate asset units",
        request=AssetGenerateSerializer,
        responses={
            201: AssetGenerateResultSerializer,
            400: OpenApiResponse(description="Invalid request, the asset_units module is off, or print_batch_id was supplied while qr_print_batches is off."),
            403: OpenApiResponse(description="Converting a quantity product to unit tracking requires edit_inventory."),
            404: OpenApiResponse(description="Product not found in the authorized makerspace scope."),
            409: OpenApiResponse(ErrorSerializer, description="tracking_mode_locked: the product holds stock and cannot be converted."),
            423: OpenApiResponse(ErrorSerializer, description="tenant_migration_quiesced: tenant writes are frozen for migration."),
            503: OpenApiResponse(ErrorSerializer, description="tenant_migration_gate_unavailable: the source gate could not prove the write is safe."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        product = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, InventoryProduct.objects.all()), pk=pk)
        require_module(product.makerspace, "asset_units")
        serializer = AssetGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created, batch = services.generate_assets_with_qr(request.user, product, serializer.validated_data)
        return Response(
            {
                "assets": [
                    {"id": pair["asset"].id, "asset_tag": pair["asset"].asset_tag, "qr": QrCodeSerializer(pair["qr"]).data}
                    for pair in created
                ],
                "print_batch_id": batch.id if batch else None,
            },
            status=status.HTTP_201_CREATED,
        )


class AssetQrView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = EmptySerializer

    @extend_schema(
        tags=["Asset units"], summary="Create asset QR code", request=EmptySerializer,
        responses={
            201: QrCodeSerializer, **BATCH_ERRORS,
            423: OpenApiResponse(ErrorSerializer, description="tenant_migration_quiesced: tenant writes are frozen for migration."),
            503: OpenApiResponse(ErrorSerializer, description="tenant_migration_gate_unavailable: the source gate could not prove the write is safe."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        actor = current_qr_actor(request.user)
        asset = get_object_or_404(rbac.scope_by_action(actor, rbac.Action.MANAGE_QR, InventoryAsset.objects.all()), pk=pk)
        initial_makerspace_id, initial_asset_id = asset.makerspace_id, asset.id
        require_module(asset.makerspace, "asset_units")
        with qr_write([initial_makerspace_id]):
            # Permit transfer FK checks while serializing module uninstall.
            require_module_locked(initial_makerspace_id, "asset_units", no_key=True)
            # Canonical rebind and checkout also lock the QR before its asset.
            qr = QrCode.objects.select_for_update().filter(
                makerspace_id=initial_makerspace_id,
                target_type=QrCode.TargetType.ASSET,
                target_id=initial_asset_id,
                status=QrCode.Status.ACTIVE,
            ).first()
            actor = current_qr_actor(actor)
            asset = get_object_or_404(
                rbac.scope_by_action(actor, rbac.Action.MANAGE_QR, InventoryAsset.objects.select_for_update()),
                pk=initial_asset_id, makerspace_id=initial_makerspace_id,
            )
            actor = current_qr_actor(actor)
            require_action(actor, rbac.Action.MANAGE_QR, initial_makerspace_id)
            created = False
            if qr is None:
                qr, created = QrCode.objects.get_or_create(
                    makerspace=asset.makerspace,
                    target_type=QrCode.TargetType.ASSET,
                    target_id=asset.id,
                    status=QrCode.Status.ACTIVE,
                    defaults={"created_by": actor},
                )
            if created:
                audit.record(actor, "qr.created", makerspace=asset.makerspace, target=qr)
        return Response(QrCodeSerializer(qr).data, status=status.HTTP_201_CREATED)
