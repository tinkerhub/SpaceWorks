"""Allowlisted public type eligibility shared by catalog and real intake."""
from types import SimpleNamespace

from django.db.models import Q
from rest_framework.exceptions import NotFound

from apps.machines.metering import ConsumablePoolUnit
from apps.machines.models import Machine, MachineConsumablePool, MachineType
from apps.machines.service_file_policies import policy_for_queue
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_queryset


PUBLIC_PROPOSAL_STATUSES = (Machine.Status.IDLE, Machine.Status.RUNNING, Machine.Status.RESERVED)


def require_public_service(makerspace):
    if (
        not servable_queryset(type(makerspace).objects.filter(pk=makerspace.pk)).exists()
        or not makerspace.public_inventory_enabled
        or not all(module_enabled(makerspace, key) for key in ("machines", "machine_service"))
    ):
        raise NotFound()


def eligible_public_machines(makerspace):
    return Machine.objects.filter(
        makerspace=makerspace, is_active=True, is_public=True,
        status__in=PUBLIC_PROPOSAL_STATUSES,
    )


def public_service_types(makerspace):
    require_public_service(makerspace)
    rows = MachineType.objects.filter(
        Q(makerspace__isnull=True) | Q(makerspace=makerspace),
        pk__in=eligible_public_machines(makerspace).values("machine_type_id"),
    )
    if not module_enabled(makerspace, "printing"):
        rows = rows.exclude(makerspace__isnull=True, slug="3d_printer")
    return rows.order_by("name", "pk")


def resolve_public_service_type(makerspace, type_id):
    row = public_service_types(makerspace).filter(pk=type_id).first()
    if row is None:
        raise NotFound("Public machine service type is unavailable.")
    return row


def public_type_policy(machine_type):
    return policy_for_queue(SimpleNamespace(machine_type=machine_type))


def eligible_public_pools(makerspace, machine_type):
    """Only explicitly public, compatible type stock or published machine stock."""
    config = machine_type.capability_config
    materials, colors = Q(pk__in=[]), Q(pk__in=[])
    for material in config.get("accepted_materials", []):
        materials |= Q(material__iexact=material)
    for color in config.get("accepted_colours", []):
        colors |= Q(color__iexact=color)
    return MachineConsumablePool.objects.filter(
        Q(machine__isnull=True, machine_type=machine_type)
        | (Q(machine__in=eligible_public_machines(makerspace).filter(machine_type=machine_type))
           & (Q(machine_type__isnull=True) | Q(machine_type=machine_type))),
        materials, colors,
        makerspace=makerspace, is_active=True, is_public=True,
        remaining_grams__gt=0, unit=ConsumablePoolUnit.GRAMS,
    ).order_by("material", "color", "pk")
