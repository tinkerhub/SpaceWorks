from contextlib import contextmanager

from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView


class ContainerPagination(PageNumberPagination):
    # Opt-in larger pages (?page_size=) so callers that need the FULL container list
    # (the direct-handout dropdown + its scan-membership check) aren't capped at page one.
    page_size_query_param = "page_size"
    max_page_size = 1000

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.boxes.serializers import BoxSerializer
from apps.makerspaces.guards import require_module, require_module_locked
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from apps.operations.serializers import (
    ContainerContentsSerializer,
    ContainerHistorySerializer,
    ContainerMoveSerializer,
    GenericObjectSerializer,
)


def _with_active_box_qr(queryset):
    active_qr = QrCode.objects.filter(
        makerspace_id=OuterRef("makerspace_id"),
        target_type=QrCode.TargetType.BOX,
        target_id=OuterRef("pk"),
        status=QrCode.Status.ACTIVE,
    ).order_by("id").values("id")[:1]
    return queryset.annotate(_active_qr_code_id=Subquery(active_qr))


def _fresh_parent(parent, makerspace_id):
    if parent is None:
        return None
    fresh = Box.objects.filter(pk=parent.pk, makerspace_id=makerspace_id).first()
    if fresh is None:
        raise ValidationError({"parent": "Select an existing parent in this makerspace."})
    return fresh


@contextmanager
def _duplicate_label_as_400():
    # `uniq_box_label_per_makerspace` (or a race past full_clean) was a bare 500; the
    # savepoint keeps the outer transaction usable. Same message as CreateBoxQrView.
    try:
        with transaction.atomic():
            yield
    except IntegrityError:
        raise ValidationError({"label": ["A container with this label already exists in this makerspace."]})


@extend_schema_view(
    get=extend_schema(tags=["Containers"], summary="List containers", request=None, responses={200: BoxSerializer(many=True)}),
    post=extend_schema(tags=["Containers"], summary="Create container", request=BoxSerializer, responses={201: BoxSerializer}),
)
class ContainerListCreateView(generics.ListCreateAPIView):
    serializer_class = BoxSerializer
    permission_classes = [IsActiveStaff]
    pagination_class = ContainerPagination

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "containers")
        require_action(self.request.user, rbac.Action.VIEW_INVENTORY, makerspace_id)
        return _with_active_box_qr(Box.objects.filter(makerspace_id=makerspace_id)).order_by("label")

    def create(self, request, *args, **kwargs):
        # The module answer wins before payload validation, like every other module gate.
        require_module(self.kwargs["makerspace_id"], "containers")
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        makerspace_id = self.kwargs["makerspace_id"]
        require_action(self.request.user, rbac.Action.MANAGE_QR, makerspace_id)
        with boundary_tenant_write(makerspace_id), transaction.atomic():
            # Re-checked under the makerspace lock: a concurrent uninstall must not
            # leave a container (and its QR) behind for a module that is now off.
            require_module_locked(makerspace_id, "containers")
            require_action(self.request.user, rbac.Action.MANAGE_QR, makerspace_id)
            if "parent" in serializer.validated_data:
                serializer.validated_data["parent"] = _fresh_parent(
                    serializer.validated_data["parent"], makerspace_id,
                )
            with _duplicate_label_as_400():
                box = serializer.save(makerspace_id=makerspace_id)
            QrCode.objects.get_or_create(
                makerspace_id=makerspace_id,
                target_type=QrCode.TargetType.BOX,
                target_id=box.id,
                status=QrCode.Status.ACTIVE,
                defaults={"payload": box.code, "created_by": self.request.user},
            )
            audit.record(self.request.user, "container.created", makerspace=box.makerspace, target=box)


@extend_schema_view(
    get=extend_schema(tags=["Containers"], summary="Retrieve container", request=None, responses={200: BoxSerializer}),
    patch=extend_schema(
        tags=["Containers"],
        summary="Update container",
        request=BoxSerializer,
        responses={
            200: BoxSerializer,
            400: OpenApiResponse(description="Invalid field, foreign parent or a parent cycle (field -> messages)."),
        },
    ),
)
class ContainerDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = BoxSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        action = rbac.Action.MANAGE_QR if self.request.method == "PATCH" else rbac.Action.VIEW_INVENTORY
        return rbac.scope_by_action(self.request.user, action, Box.objects.all())

    def get_object(self):
        box = super().get_object()
        require_module(box.makerspace, "containers")
        return box

    def perform_update(self, serializer):
        box = serializer.instance
        with boundary_tenant_write(box.makerspace_id), transaction.atomic():
            require_module_locked(box.makerspace_id, "containers")
            box = get_object_or_404(self.get_queryset(), pk=box.pk, makerspace_id=box.makerspace_id)
            serializer.instance = box
            if "parent" in serializer.validated_data:
                serializer.validated_data["parent"] = _fresh_parent(
                    serializer.validated_data["parent"], box.makerspace_id,
                )
            for field, value in serializer.validated_data.items():
                setattr(box, field, value)
            box.full_clean()  # parent cycles; a Django ValidationError maps to a typed 400
            with _duplicate_label_as_400():
                box = serializer.save()
            audit.record(
                self.request.user,
                "container.updated",
                makerspace=box.makerspace,
                target=box,
                meta={"fields": sorted(serializer.validated_data)},
            )


class ContainerMoveView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Containers"],
        summary="Move or update container",
        request=ContainerMoveSerializer,
        responses={
            200: BoxSerializer,
            400: OpenApiResponse(description="Invalid field, parent cycle, or the containers module is off."),
            403: OpenApiResponse(description="Permission denied."),
            404: OpenApiResponse(description="Container or parent not found in scope."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        box = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, Box.objects.all()), pk=pk)
        require_module(box.makerspace, "containers")
        serializer = ContainerMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with boundary_tenant_write(box.makerspace_id), transaction.atomic():
            # Makerspace row first (the module_install lock), so an uninstall that
            # committed after the check above cannot be raced by this move.
            require_module_locked(box.makerspace_id, "containers")
            box = get_object_or_404(
                rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, Box.objects.all()),
                pk=pk, makerspace_id=box.makerspace_id,
            )
            if "parent_id" in data:
                box.parent = None if data["parent_id"] is None else get_object_or_404(Box, pk=data["parent_id"], makerspace=box.makerspace)
            for field in ("label", "location", "description", "is_active"):
                if field in data:
                    setattr(box, field, data[field])
            box.full_clean()
            with _duplicate_label_as_400():
                box.save()
            audit.record(request.user, "container.moved", makerspace=box.makerspace, target=box)
        return Response(BoxSerializer(box).data)


class ContainerContentsView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = GenericObjectSerializer

    @extend_schema(tags=["Containers"], summary="Get container contents", request=None, responses={200: ContainerContentsSerializer})
    def get(self, request, pk, *args, **kwargs):
        queryset = _with_active_box_qr(
            rbac.scope_by_action(request.user, rbac.Action.VIEW_INVENTORY, Box.objects.all())
        )
        box = get_object_or_404(queryset, pk=pk)
        require_module(box.makerspace, "containers")
        children = _with_active_box_qr(box.children.all()).order_by("label")
        return Response(
            {
                "container": BoxSerializer(box).data,
                "products": [
                    {"id": p.id, "name": p.name, "available_quantity": p.available_quantity, "tracking_mode": p.tracking_mode}
                    for p in box.products.filter(is_archived=False).order_by("name")
                ],
                "assets": [
                    {"id": a.id, "asset_tag": a.asset_tag, "product": a.product.name, "status": a.status}
                    for a in box.assets.select_related("product").order_by("asset_tag")
                ],
                "children": BoxSerializer(children, many=True).data,
            }
        )


class ContainerHistoryView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = GenericObjectSerializer

    @extend_schema(tags=["Containers"], summary="Get container scan history", request=None, responses={200: ContainerHistorySerializer})
    def get(self, request, pk, *args, **kwargs):
        box = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.VIEW_INVENTORY, Box.objects.all()), pk=pk)
        require_module(box.makerspace, "containers")
        qr_scans = [
            {
                "id": f"qr:{scan.id}",
                "source": "qr_scan_event",
                "context": scan.context,
                "actor": scan.actor_id,
                "created_at": scan.created_at,
            }
            for scan in QrScanEvent.objects.filter(
                makerspace=box.makerspace,
                qr_code__target_type=QrCode.TargetType.BOX,
                qr_code__target_id=box.id,
            ).order_by("-created_at")[:100]
        ]
        box_scans = [
            {
                "id": f"box:{scan.id}",
                "source": "box_scan",
                "context": scan.context,
                "actor": scan.actor_id,
                "created_at": scan.created_at,
            }
            for scan in BoxScan.objects.filter(
                makerspace=box.makerspace,
                box=box,
            ).order_by("-created_at")[:100]
        ]
        scans = sorted(
            [*qr_scans, *box_scans],
            key=lambda scan: scan["created_at"],
            reverse=True,
        )[:100]
        return Response({"container": box.id, "scans": scans})
