"""The one resolver for a machine type's structural settings inside one makerspace.

A custom (makerspace-local) type carries its settings in its own `capability_config`. A
global built-in type is shared by every makerspace, so a makerspace changes it only through
the override columns on its `MakerspaceMachineTypePricing` row. Every reader of the metering
unit, booking or consumables setting goes through here; nothing else may read
`capability_config["metering_unit"]` directly, or the override would apply in some places
and silently not in others.
"""

from rest_framework.exceptions import ValidationError

from apps.machines.metering import MeteringUnit, pool_unit_for_metering
from apps.machines.models import MakerspaceMachineTypePricing

# Setting name -> override column on MakerspaceMachineTypePricing.
OVERRIDE_COLUMNS = {
    "metering_unit": "metering_unit_override",
    "requires_booking": "requires_booking_override",
    "uses_consumables": "uses_consumables_override",
}
_UNSET = object()


def settings_from_config(config, overrides=None):
    """Resolve settings from a capability config plus optional non-null overrides."""
    config = config or {}
    unit = config.get("metering_unit")
    result = {
        # Weight is what an unnamed unit meant before types named one (the printer default).
        "metering_unit": unit if unit in MeteringUnit.values else MeteringUnit.WEIGHT,
        "requires_booking": config.get("requires_booking") is True,
        "uses_consumables": config.get("uses_consumables") is not False,
    }
    overridden = False
    for key, value in (overrides or {}).items():
        if value is not None:
            result[key] = value
            overridden = True
    if result["metering_unit"] == MeteringUnit.MINUTES:
        # Time is not drawn from a stock pool, whatever the stored switch says.
        result["uses_consumables"] = False
    result["overridden"] = overridden
    return result


def _resolve(machine_type, row):
    overrides = None
    if row is not None and machine_type.makerspace_id is None:
        overrides = {key: getattr(row, column, None) for key, column in OVERRIDE_COLUMNS.items()}
    return settings_from_config(machine_type.capability_config, overrides)


def override_row(machine_type, makerspace_id):
    if machine_type.makerspace_id is not None or makerspace_id is None:
        return None
    return MakerspaceMachineTypePricing.objects.filter(
        makerspace_id=makerspace_id, machine_type_id=machine_type.pk
    ).first()


def effective_type_config(machine_type, makerspace_id, *, row=_UNSET):
    """`{metering_unit, requires_booking, uses_consumables, overridden}` for one makerspace.

    Pass `row` when the caller already holds the type's pricing row (or knows there is none)
    to save the lookup.
    """
    if row is _UNSET:
        row = override_row(machine_type, makerspace_id)
    return _resolve(machine_type, row)


def effective_type_configs(machine_types, makerspace_id):
    """Bulk form for list responses: `{machine_type_id: config}` in two queries at most."""
    machine_types = list(machine_types)
    global_ids = [row.pk for row in machine_types if row.makerspace_id is None]
    rows = {}
    if global_ids and makerspace_id is not None:
        rows = {
            row.machine_type_id: row
            for row in MakerspaceMachineTypePricing.objects.filter(
                makerspace_id=makerspace_id, machine_type_id__in=global_ids
            )
        }
    return {row.pk: _resolve(row, rows.get(row.pk)) for row in machine_types}


def effective_metering_unit(machine_type, makerspace_id, *, row=_UNSET):
    return effective_type_config(machine_type, makerspace_id, row=row)["metering_unit"]


def type_pool_unit(machine_type, makerspace_id, requested=None):
    """The pool unit a type's stock must use here; refuses types that take no consumables."""
    settings = effective_type_config(machine_type, makerspace_id)
    derived = pool_unit_for_metering(settings["metering_unit"]) if settings["uses_consumables"] else None
    if derived is None:
        raise ValidationError({"machine_type": "This machine type does not use consumable pools."})
    if requested is not None and requested != derived:
        raise ValidationError({"unit": f"Consumable pools for this machine type use {derived}."})
    return derived


def cached_effective_config(context, machine_type, makerspace_id):
    """Serializer helper: memoise per (type, makerspace) in the shared serializer context."""
    cache = context.setdefault("_effective_type_configs", {}) if isinstance(context, dict) else {}
    key = (machine_type.pk, makerspace_id)
    if key not in cache:
        cache[key] = effective_type_config(machine_type, makerspace_id)
    return cache[key]
