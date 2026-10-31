"""Exact provider minor-unit conversion within the two-decimal Payment ledger."""

from decimal import Decimal, DecimalException, ROUND_HALF_UP

from apps.payments.currency_rules import PROVIDER_CURRENCY_UNITS, SUPPORTED_CURRENCIES
from apps.payments.stripe_client import PaymentsUnavailable


def normalize_currency(currency):
    if not isinstance(currency, str):
        raise PaymentsUnavailable("Unsupported payment currency.")
    currency = currency.lower()
    if currency not in SUPPORTED_CURRENCIES:
        raise PaymentsUnavailable("Unsupported payment currency.")
    return currency


def _currency_units(currency, provider):
    if not isinstance(provider, str) or provider not in PROVIDER_CURRENCY_UNITS:
        raise PaymentsUnavailable("Unsupported payment provider.")
    currency = normalize_currency(currency)
    units = PROVIDER_CURRENCY_UNITS[provider].get(currency)
    if units is None:
        raise PaymentsUnavailable("Unsupported payment currency.")
    return units


def normalize_major_amount(amount):
    """Reject invalid ledger values rather than letting the database round them."""
    try:
        value = Decimal(str(amount))
        if not value.is_finite() or not 0 < value <= Decimal("9999999999.99"):
            raise PaymentsUnavailable("Invalid payment amount.")
        normalized = value.quantize(Decimal("0.01"))
        if normalized != value:
            raise PaymentsUnavailable("Unsupported payment amount precision.")
        return normalized
    except (DecimalException, ValueError, TypeError):
        raise PaymentsUnavailable("Invalid payment amount.") from None


def to_minor_units(amount, currency, provider="stripe"):
    scale, quantum = _currency_units(currency, provider)
    value = normalize_major_amount(amount) * scale
    if value != value.to_integral_value() or value % quantum:
        raise PaymentsUnavailable("Unsupported payment amount precision.")
    return int(value)


def application_fee_amount(amount, basis_points, currency="inr", provider="stripe"):
    """Round fees HALF_UP on the ledger-compatible quantum and cap at the charge."""
    charge = to_minor_units(amount, currency, provider)
    _, quantum = _currency_units(currency, provider)
    try:
        rate = Decimal(str(basis_points))
        if not rate.is_finite() or rate < 0:
            raise PaymentsUnavailable("Invalid payment fee.")
        fee = (Decimal(charge) * rate / Decimal(10000) / quantum).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        ) * quantum
        return min(charge, int(fee))
    except (DecimalException, ValueError, TypeError):
        raise PaymentsUnavailable("Invalid payment fee.") from None


def validate_payment_amount(payment):
    """Validate immutable pending financial data before any external operation."""
    charge = to_minor_units(payment.amount, payment.currency, payment.provider)
    _, quantum = _currency_units(payment.currency, payment.provider)
    fee = payment.stripe_application_fee_amount
    if not isinstance(fee, int) or not 0 <= fee <= charge or fee % quantum:
        raise PaymentsUnavailable("Invalid stored payment fee.")
    return charge
