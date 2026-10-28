from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_machine_type_pricing import (
    MachineTypePricingListSerializer, MachineTypePricingSerializer, MachineTypePricingSetSerializer,
)
from apps.audit import services as audit
from apps.machines import role_scope
from apps.machines.models import MachineType, MakerspaceMachineTypePricing
from apps.machines.service_pricing import default_free_below
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.payments.models import MakerspacePaymentSettings


def _types(makerspace_id):
    return MachineType.objects.filter(Q(makerspace__isnull=True) | Q(makerspace_id=makerspace_id))


def _priced_types(actor, makerspace_id):
    """Space managers price every type; machine staff price only the types they manage.

    A Machine Manager (or a role scoped to one type) sets the rate and free threshold its
    manual usage is logged at, but a role scoped to the laser must not see or change what the
    printers cost. Turning online payment on or off stays a space-manager decision.
    """
    require_module(makerspace_id, "machines")
    if rbac.is_space_manager_identity(actor, makerspace_id):
        return _types(makerspace_id)
    if not rbac.can(actor, rbac.Action.MANAGE_MACHINES, makerspace_id):
        raise PermissionDenied()
    # A price is per type, so only a type link reaches it: a role linked to one machine
    # must not reprice every other machine of that type (`scope_covers_type`'s rule).
    scope = role_scope.scope_q_for(role_scope.manage_scope_for(actor, makerspace_id), type_id_paths=("id",))
    return _types(makerspace_id).filter(scope)


class MachineTypePricingListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machines"], summary="List makerspace machine-type pricing", responses={200: MachineTypePricingListSerializer, 403: OpenApiResponse(description="Space-manager identity or machine management required.")})
    def get(self, request, makerspace_id):
        machine_types = list(_priced_types(request.user, makerspace_id).only("id", "makerspace_id", "capability_config"))
        pricing_by_type = {row.machine_type_id: row for row in MakerspaceMachineTypePricing.objects.filter(makerspace_id=makerspace_id, machine_type_id__in=[row.pk for row in machine_types])}
        rows = [pricing_by_type.get(row.pk) or MakerspaceMachineTypePricing(makerspace_id=makerspace_id, machine_type_id=row.pk, free_below_quantity=default_free_below(row, makerspace_id, row=None)) for row in machine_types]
        makerspace = get_object_or_404(Makerspace.objects.all(), pk=makerspace_id)
        return Response({"currency": MakerspacePaymentSettings.for_makerspace(makerspace).default_currency, "results": MachineTypePricingSerializer(rows, many=True).data})


class MachineTypePricingDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machines"], summary="Set makerspace machine-type pricing", request=MachineTypePricingSetSerializer, responses={200: MachineTypePricingSerializer, 400: OpenApiResponse(description="Invalid price."), 403: OpenApiResponse(description="Machine management for this type required; online payment needs space-manager identity."), 404: OpenApiResponse(description="Machine type not found.")})
    def put(self, request, makerspace_id, machine_type_id):
        machine_type = get_object_or_404(_priced_types(request.user, makerspace_id), pk=machine_type_id)
        serializer = MachineTypePricingSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            current = MakerspaceMachineTypePricing.objects.select_for_update().filter(
                makerspace_id=makerspace_id, machine_type=machine_type
            ).first()
            was_enabled = bool(current and current.payment_enabled)
            if serializer.validated_data["payment_enabled"] != was_enabled and not rbac.is_space_manager_identity(request.user, makerspace_id):
                raise PermissionDenied("Only a space manager can turn online payment on or off.")
            row, created = MakerspaceMachineTypePricing.objects.get_or_create(
                makerspace_id=makerspace_id, machine_type=machine_type,
                defaults={"free_below_quantity": default_free_below(machine_type, makerspace_id, row=None), **serializer.validated_data, "created_by": request.user, "updated_by": request.user},
            )
            if not created:
                # No row to lock above means a concurrent first save may have made it since;
                # re-check the switch against what is stored now.
                if serializer.validated_data["payment_enabled"] != row.payment_enabled and not rbac.is_space_manager_identity(request.user, makerspace_id):
                    raise PermissionDenied("Only a space manager can turn online payment on or off.")
                for field, value in serializer.validated_data.items():
                    setattr(row, field, value)
                row.updated_by = request.user
                row.save(update_fields=[*serializer.validated_data.keys(), "updated_by", "updated_at"])
            audit.record(request.user, "machine_type_pricing.set" if created else "machine_type_pricing.updated", makerspace=row.makerspace, target=row, target_type="machine_type_pricing", meta={"machine_type_id": machine_type.pk, "payment_enabled": row.payment_enabled, "rate_per_unit": str(row.rate_per_unit), "flat_fee": str(row.flat_fee), "free_below_quantity": str(row.free_below_quantity)})
        return Response(MachineTypePricingSerializer(row).data)
