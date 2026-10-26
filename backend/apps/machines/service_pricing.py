"""Job pricing is a job fact and must work without the payments module installed."""

from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from apps.machines.metering import MeteringUnit, metering_unit_for_pool
from apps.machines.models import MakerspaceMachineTypePricing


def effective_quantity(service_request, machine_type):
    config = machine_type.capability_config or {}
    if config.get("metering_unit") == "minutes":
        return _decimal(service_request.actual_minutes)
    quantity = service_request.actual_consumed_quantity
    if quantity is not None:
        return _decimal(quantity)
    return _decimal(service_request.actual_consumed_grams)


def compute_amount(service_request):
    assigned_machine = service_request.assigned_machine
    if assigned_machine is None:
        return Decimal("0.00")

    machine_type = assigned_machine.machine_type
    pricing = MakerspaceMachineTypePricing.objects.filter(
        makerspace=service_request.makerspace,
        machine_type=machine_type,
        payment_enabled=True,
    ).first()
    if pricing is None:
        return Decimal("0.00")

    amount = pricing.rate_per_unit * effective_quantity(service_request, machine_type) + pricing.flat_fee
    if amount <= 0:
        return Decimal("0.00")
    return amount.quantize(Decimal("0.01"))


def machine_type_metering_unit(machine_type):
    # Every seeded type names its unit; weight is the printer default an unnamed one meant.
    return (machine_type.capability_config or {}).get("metering_unit") or MeteringUnit.WEIGHT


def default_free_below(machine_type):
    """Starting free threshold for a type's pricing: 20 g for weight-metered printers."""
    return Decimal("20") if machine_type_metering_unit(machine_type) == MeteringUnit.WEIGHT else Decimal("0")


def manual_usage_price(machine, *, duration_minutes, grams=0, quantity=None, metering_unit=None, pool=None, **_):
    """Auto price for a manual run, or None when the type has no pricing to apply.

    Time-metered types price the run's minutes; everything else prices what it consumed.
    Either way, an amount under the type's `free_below_quantity` (same unit) is free. This is
    only the price that is logged; nothing is charged. Queue jobs keep `compute_amount`.
    """
    pricing = MakerspaceMachineTypePricing.objects.filter(
        makerspace_id=machine.makerspace_id, machine_type_id=machine.machine_type_id
    ).first()
    if pricing is None or (pricing.rate_per_unit <= 0 and pricing.flat_fee <= 0):
        return None
    type_unit = machine_type_metering_unit(machine.machine_type)
    if type_unit == MeteringUnit.MINUTES:
        amount_of = _decimal(duration_minutes)
    else:
        unit = metering_unit or (metering_unit_for_pool(pool.unit) if pool else None) or MeteringUnit.WEIGHT
        if unit != type_unit:
            # The rate is per unit of the type; 10 ml priced per gram (or let in under the
            # free weight) would log a wrong price, not a rounding difference.
            raise ValidationError({"metering_unit": "Usage unit does not match this machine type's pricing unit."})
        amount_of = _decimal(grams if quantity is None else quantity)
    if amount_of < pricing.free_below_quantity:
        return Decimal("0.00")
    amount = pricing.rate_per_unit * amount_of + pricing.flat_fee
    if amount >= _MAX_LOGGED_PRICE:
        # `MachineUsageEntry.price` is numeric(12, 2); a huge quantity must be a 400, not
        # a database overflow.
        raise ValidationError({"price": "The auto price is too large to log. Type the price instead."})
    return amount.quantize(Decimal("0.01")) if amount > 0 else Decimal("0.00")


# The smallest amount that rounds past numeric(12, 2)'s 9999999999.99.
_MAX_LOGGED_PRICE = Decimal("9999999999.995")


def _decimal(value):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")
