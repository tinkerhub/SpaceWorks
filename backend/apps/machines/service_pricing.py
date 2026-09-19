"""Job pricing is a job fact and must work without the payments module installed."""

from decimal import Decimal, InvalidOperation

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


def _decimal(value):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")
