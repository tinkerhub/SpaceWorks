from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.warranty.serializers import WarrantySerializer, WarrantyUpsertSerializer
from apps.warranty.views_report import MakerspaceWarrantyReportView
from apps.warranty.access import (
    resolve_asset_host,
    resolve_machine_host,
)
from apps.audit import services as audit
from apps.makerspaces.guards import require_module, require_module_locked
from apps.machines import access as machine_access
from apps.warranty.models import Warranty


ERRORS = {401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer}


class AssetWarrantyView(APIView):
    permission_classes = [IsActiveStaff]

    def _asset(self, request, pk):
        asset = resolve_asset_host(request.user, pk)
        require_action(request.user, rbac.Action.EDIT_INVENTORY, asset.makerspace_id)
        require_module(asset.makerspace_id, "staff_admin")
        return asset

    @extend_schema(
        tags=["Admin warranty"],
        summary="Retrieve warranty details for an inventory asset",
        responses={200: WarrantySerializer, **ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        asset = self._asset(request, pk)
        warranty = _asset_warranty(asset)
        if warranty is None:
            return Response(None)
        return Response(WarrantySerializer(warranty).data)

    @extend_schema(
        tags=["Admin warranty"],
        summary="Create or update warranty details for an inventory asset",
        request=WarrantyUpsertSerializer,
        responses={
            200: WarrantySerializer,
            400: OpenApiResponse(description="Invalid warranty details."),
            **ERRORS,
        },
    )
    def put(self, request, pk, *args, **kwargs):
        asset = self._asset(request, pk)
        serializer = WarrantyUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        warranty, _created = _upsert_warranty(
            actor=request.user,
            asset=asset,
            data=serializer.validated_data,
        )
        return Response(WarrantySerializer(_reload_warranty(warranty)).data)


class MachineWarrantyView(APIView):
    permission_classes = [IsActiveStaff]

    def _machine(self, request, pk):
        machine = resolve_machine_host(request.user, pk)
        if not machine_access.can_manage_machine(request.user, machine):
            raise PermissionDenied()
        require_module(machine.makerspace_id, "machines")
        return machine

    @extend_schema(
        tags=["Admin warranty"],
        summary="Retrieve warranty details for a machine",
        responses={200: WarrantySerializer, **ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        machine = self._machine(request, pk)
        warranty = _machine_warranty(machine)
        if warranty is None:
            return Response(None)
        return Response(WarrantySerializer(warranty).data)

    @extend_schema(
        tags=["Admin warranty"],
        summary="Create or update warranty details for a machine",
        request=WarrantyUpsertSerializer,
        responses={
            200: WarrantySerializer,
            400: OpenApiResponse(description="Invalid warranty details."),
            **ERRORS,
        },
    )
    def put(self, request, pk, *args, **kwargs):
        machine = self._machine(request, pk)
        serializer = WarrantyUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        warranty, _created = _upsert_warranty(
            actor=request.user,
            machine=machine,
            data=serializer.validated_data,
        )
        return Response(WarrantySerializer(_reload_warranty(warranty)).data)


def _asset_warranty(asset):
    return _host_warranty("asset", asset)



def _machine_warranty(machine):
    return _host_warranty("machine", machine)


def _host_warranty(host_kind, host):
    return (
        Warranty.objects.select_related("asset", "machine")
        .prefetch_related("documents")
        .filter(**{host_kind: host})
        .first()
    )


def _reload_warranty(warranty):
    return (
        Warranty.objects.select_related("asset", "machine")
        .prefetch_related("documents")
        .get(pk=warranty.pk)
    )


@transaction.atomic
def _upsert_warranty(*, actor, data, asset=None, machine=None):
    hosts = {
        kind: host
        for kind, host in (("asset", asset), ("machine", machine))
        if host is not None
    }
    if len(hosts) != 1:
        raise ValueError("Exactly one warranty host is required.")
    host_kind, host = next(iter(hosts.items()))
    makerspace = require_module_locked(
        host.makerspace_id, "machines" if host_kind == "machine" else "staff_admin",
        no_key=True,
    )
    # Lock the concrete host even before a warranty exists, so two first PUTs
    # serialize on the same row. Avoid locking nullable host joins on Warranty.
    host = get_object_or_404(
        type(host).objects.select_for_update(), pk=host.pk, makerspace=makerspace,
    )
    warranty = Warranty.objects.select_for_update().filter(**{host_kind: host}).first()
    if host_kind == "machine":
        host = resolve_machine_host(actor, host.pk)
        if not machine_access.can_manage_machine(actor, host):
            raise PermissionDenied()
    else:
        host = resolve_asset_host(actor, host.pk)
        require_action(actor, rbac.Action.EDIT_INVENTORY, host.makerspace_id)
    created = warranty is None
    if created:
        warranty = Warranty(makerspace=makerspace, **{host_kind: host})
    warranty.makerspace = makerspace
    for field in ("purchased_on", "warranty_expires_on", "vendor_name", "vendor_contact"):
        if field in data:
            setattr(warranty, field, data[field])
    try:
        warranty.full_clean()
    except DjangoValidationError as exc:
        raise ValidationError(getattr(exc, "message_dict", exc.messages)) from exc
    warranty.save()
    audit.record(
        actor,
        "warranty.created" if created else "warranty.updated",
        makerspace=makerspace,
        target=warranty,
    )
    return warranty, created

__all__ = [
    "AssetWarrantyView",
    "MachineWarrantyView",
    "MakerspaceWarrantyReportView",
]
