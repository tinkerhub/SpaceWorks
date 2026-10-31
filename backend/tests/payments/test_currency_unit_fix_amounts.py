"""Currency contracts for a two-decimal ledger and integer provider payloads."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.payments.amounts import (
    application_fee_amount,
    normalize_currency,
    normalize_major_amount,
    to_minor_units,
    validate_payment_amount,
)
from apps.payments.stripe_client import PaymentsUnavailable


def test_ordinary_currency_units_are_exact_decimal_cents():
    for currency in ("USD", "INR", "EUR", "GBP", "AUD", "CAD"):
        assert normalize_currency(currency) == currency.lower()
        for provider in ("stripe", "razorpay"):
            assert to_minor_units(Decimal("0.29"), currency, provider) == 29
            assert to_minor_units(Decimal("10.29"), currency, provider) == 1029
            assert to_minor_units(Decimal("9999999999.99"), currency, provider) == 999999999999
    normalized = normalize_major_amount(Decimal("0.29"))
    assert isinstance(normalized, Decimal)
    assert normalized == Decimal("0.29")


def test_zero_decimal_and_legacy_currency_units_are_provider_specific():
    for currency in ("jpy", "krw"):
        for provider in ("stripe", "razorpay"):
            assert to_minor_units(Decimal("10.00"), currency, provider) == 10
    for currency in ("isk", "ugx"):
        assert to_minor_units(Decimal("10.00"), currency, "stripe") == 1000
        assert to_minor_units(Decimal("10.00"), currency, "razorpay") == 10


def test_whole_major_currencies_reject_fractions_on_both_providers():
    for currency in ("jpy", "krw", "isk", "ugx"):
        for provider in ("stripe", "razorpay"):
            with pytest.raises(PaymentsUnavailable):
                to_minor_units(Decimal("10.01"), currency, provider)


def test_currency_policy_rejects_unknown_codes_types_and_unsupported_provider_codes():
    for currency in ("xyz", "", None, 123):
        with pytest.raises(PaymentsUnavailable):
            normalize_currency(currency)
        with pytest.raises(PaymentsUnavailable):
            to_minor_units(Decimal("10"), currency)
    with pytest.raises(PaymentsUnavailable):
        to_minor_units(Decimal("10"), "usd", "unknown-provider")
    for provider, currency in (("stripe", "iqd"), ("razorpay", "afn")):
        with pytest.raises(PaymentsUnavailable):
            to_minor_units(Decimal("10"), currency, provider)


def test_invalid_nonfinite_nonpositive_and_overprecision_amounts_are_rejected():
    for amount in (
        None, True, "invalid", "", Decimal("NaN"), Decimal("sNaN"),
        Decimal("Infinity"), Decimal("-Infinity"), Decimal("0"),
        Decimal("-0.01"), Decimal("1.001"), Decimal("10000000000"),
    ):
        with pytest.raises(PaymentsUnavailable):
            to_minor_units(amount, "usd")


def test_fee_rounding_uses_half_up_and_caps_at_the_charge():
    # Explicit monetary outcomes, including a cents tie and a large exact Decimal.
    for amount, bps, expected in (
        ("0.01", "5000", 1), ("10.01", "125", 13),
        ("0.29", "5000", 15), ("10", "0", 0),
        ("10", "10000", 1000), ("10", "25000", 1000),
        ("9999999999.99", "125", 12500000000),
    ):
        assert application_fee_amount(Decimal(amount), Decimal(bps), "usd") == expected


def test_zero_decimal_and_special_currency_fees_obey_their_quantum():
    for currency in ("jpy", "krw"):
        assert application_fee_amount(Decimal("10"), 499, currency) == 0
        assert application_fee_amount(Decimal("10"), 500, currency) == 1
        assert application_fee_amount(Decimal("10"), 20000, currency) == 10
    for currency in ("isk", "ugx"):
        assert application_fee_amount(Decimal("10"), 499, currency, "stripe") == 0
        assert application_fee_amount(Decimal("10"), 500, currency, "stripe") == 100
        assert application_fee_amount(Decimal("10"), 20000, currency, "stripe") == 1000
        assert application_fee_amount(Decimal("10"), 500, currency, "razorpay") == 1


def test_invalid_fee_rates_are_rejected():
    for bps in (None, "invalid", Decimal("NaN"), Decimal("Infinity"), -1):
        with pytest.raises(PaymentsUnavailable):
            application_fee_amount(Decimal("10"), bps, "usd")


def test_stored_fee_validation_rejects_charge_overflow_and_special_fraction():
    for currency, fee in (("jpy", 11), ("usd", 1001), ("isk", 1), ("ugx", 101)):
        payment = SimpleNamespace(
            amount=Decimal("10"), currency=currency, provider="stripe",
            stripe_application_fee_amount=fee,
        )
        with pytest.raises(PaymentsUnavailable, match="stored payment fee"):
            validate_payment_amount(payment)
    for currency, fee, charge in (("jpy", 0, 10), ("isk", 100, 1000), ("usd", 13, 1000)):
        assert validate_payment_amount(SimpleNamespace(
            amount=Decimal("10"), currency=currency, provider="stripe",
            stripe_application_fee_amount=fee,
        )) == charge
