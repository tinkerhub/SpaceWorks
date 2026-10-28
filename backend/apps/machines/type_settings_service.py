"""Changing a machine type's settings in one makerspace, behind the in-flight-work guard."""

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.machines.metering import MeteringUnit, pool_unit_for_metering
from apps.machines.models import MachineConsumablePool, MachineServiceRequest, MakerspaceMachineTypePricing
from apps.machines.printer_capabilities import is_printer_type
from apps.machines.service_pricing import default_free_below
from apps.machines.type_settings import OVERRIDE_COLUMNS, effective_type_config


def _public(config):
    return {key: config[key] for key in OVERRIDE_COLUMNS}


def _active_type_pools(machine_type, makerspace_id):
    return MachineConsumablePool.objects.filter(makerspace_id=makerspace_id, is_active=True).filter(
        Q(machine_type_id=machine_type.pk) | Q(machine__machine_type_id=machine_type.pk)
    )


def assert_settings_change_allowed(machine_type, makerspace_id, old, new):
    """Refuse a change that would strand stock or a running job in the old unit."""
    if new["metering_unit"] != old["metering_unit"]:
        expected = pool_unit_for_metering(new["metering_unit"])
        pools = _active_type_pools(machine_type, makerspace_id)
        if expected is not None:
            pools = pools.exclude(unit=expected)
        if pools.exists():
            raise ValidationError({"metering_unit": (
                "This type has active consumable pools in another unit. Retire them before changing its metering unit."
            )})
        busy = MachineServiceRequest.objects.filter(makerspace_id=makerspace_id).filter(
            Q(assigned_machine__machine_type_id=machine_type.pk)
            | Q(queue__machine_type_id=machine_type.pk)
            | Q(bucket__machine__machine_type_id=machine_type.pk)
        ).filter(
            Q(status=MachineServiceRequest.Status.IN_PROGRESS) | Q(reserved_quantity__gt=0) | Q(reserved_grams__gt=0)
        )
        if busy.exists():
            raise ValidationError({"metering_unit": (
                "This type has jobs in progress or with reserved stock. Finish them before changing its metering unit."
            )})
    if old["uses_consumables"] and not new["uses_consumables"] and _active_type_pools(machine_type, makerspace_id).exists():
        raise ValidationError({"uses_consumables": (
            "This type has active consumable pools. Retire them before turning consumables off."
        )})


@transaction.atomic
def set_type_override(machine_type, makerspace, actor, values):
    """Set (or, with None, clear) a built-in type's settings for this makerspace only."""
    if machine_type.makerspace_id is not None:
        raise ValidationError("Custom machine types keep their settings on the type itself; edit the type instead.")
    if is_printer_type(machine_type):
        # The printer pack meters filament by weight and always starts a job on a spool.
        if values.get("metering_unit") not in (None, MeteringUnit.WEIGHT):
            raise ValidationError({"metering_unit": "The 3D printer is always metered by weight."})
        if values.get("uses_consumables") is False:
            raise ValidationError({"uses_consumables": "The 3D printer always uses filament pools."})
    row, created = MakerspaceMachineTypePricing.objects.get_or_create(
        makerspace=makerspace, machine_type=machine_type, defaults={"created_by": actor}
    )
    row = MakerspaceMachineTypePricing.objects.select_for_update().get(pk=row.pk)
    # Lock every active pool of the type before the in-flight check. A job reserving stock
    # locks its pool and only then reads the unit, so the two now serialize: a start that
    # got in first is seen by the busy check below, and one that waits re-reads the new
    # unit and is refused instead of reserving in the old one.
    list(_active_type_pools(machine_type, makerspace.pk).select_for_update(of=("self",)).order_by("pk").values_list("pk", flat=True))
    old = effective_type_config(machine_type, makerspace.pk, row=row)
    for key, column in OVERRIDE_COLUMNS.items():
        if key in values:
            setattr(row, column, values[key])
    new = effective_type_config(machine_type, makerspace.pk, row=row)
    assert_settings_change_allowed(machine_type, makerspace.pk, old, new)
    if created:
        # The starting threshold the pricing endpoint gives a first row, in the NEW unit.
        row.free_below_quantity = default_free_below(machine_type, makerspace.pk, row=row)
    row.updated_by = actor
    row.save()
    audit.record(
        actor, "machine_type.settings_overridden", makerspace=makerspace, target=machine_type,
        target_type="machine_type",
        meta={"machine_type_id": machine_type.pk, "old": _public(old), "new": _public(new)},
    )
    return new
