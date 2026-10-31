"""Provider facts are frozen test data, independent of production catalogues."""

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.payments.amounts import (
    application_fee_amount, normalize_currency, to_minor_units, validate_payment_amount,
)
from apps.payments.currency_rules import PROVIDER_CURRENCY_UNITS, SUPPORTED_CURRENCIES
from apps.payments.stripe_client import PaymentsUnavailable


REFERENCE = json.loads((Path(__file__).parent / "fixtures" /
                        "provider_currency_reference_20261030.json").read_text())
CATALOGUES = REFERENCE["providers"]
PAIRS = [pytest.param(provider, code, rule, id=f"{provider}-{code}")
         for provider, codes in CATALOGUES.items() for code, rule in codes.items()]
WRONG_PROVIDER = [pytest.param(other, code, id=f"{other}-rejects-{code}")
                  for provider, codes in CATALOGUES.items()
                  for other in CATALOGUES if other != provider
                  for code in codes if code not in CATALOGUES[other]]


def test_catalogues_have_exact_published_keys_and_units_without_iso_fallback():
    assert set(PROVIDER_CURRENCY_UNITS) == {"stripe", "razorpay"}
    for provider, count in (("stripe", 139), ("razorpay", 128)):
        expected = CATALOGUES[provider]
        assert len(expected) == count
        assert set(PROVIDER_CURRENCY_UNITS[provider]) == set(expected)
        assert PROVIDER_CURRENCY_UNITS[provider] == {
            code: (rule["factor"], rule["quantum"]) for code, rule in expected.items()
        }
    union = set(CATALOGUES["stripe"]) | set(CATALOGUES["razorpay"])
    assert len(union) == 147
    assert set(SUPPORTED_CURRENCIES) == union
    for provider, expected in (("stripe", (117, 15, 5, 2)), ("razorpay", (106, 16, 6, 0))):
        rules = list(CATALOGUES[provider].values())
        assert tuple(sum((r["factor"], r["quantum"]) == pair for r in rules)
                     for pair in ((100, 1), (1, 1), (1000, 10), (100, 100))) == expected


@pytest.mark.parametrize("provider,code,rule", PAIRS)
def test_every_provider_currency_converts_money_using_independent_units(provider, code, rule):
    # Whole values probe every one of the 267 published provider/code pairs.
    actual = to_minor_units(Decimal("7.00"), code.upper(), provider)
    assert type(actual) is int
    assert actual == 7 * rule["factor"]
    assert normalize_currency(code.upper()) == code
    if rule["whole_major"]:
        with pytest.raises(PaymentsUnavailable, match="precision"):
            to_minor_units(Decimal("7.01"), code, provider)
    else:
        expected = 123 * rule["factor"] // 100
        assert to_minor_units(Decimal("1.23"), code, provider) == expected
        assert to_minor_units(Decimal("1.230"), code, provider) == expected
    with pytest.raises(PaymentsUnavailable, match="precision"):
        to_minor_units(Decimal("1.234"), code, provider)


@pytest.mark.parametrize("provider,code", WRONG_PROVIDER)
def test_every_provider_only_code_is_rejected_by_the_other_provider(provider, code):
    assert normalize_currency(code) == code  # Recognized globally, unavailable on this vendor.
    with pytest.raises(PaymentsUnavailable, match="currency"):
        to_minor_units(Decimal("10"), code, provider)


@pytest.mark.parametrize("provider", [None, [], {}, "unknown", 123, True])
def test_invalid_provider_types_have_a_typed_refusal(provider):
    with pytest.raises(PaymentsUnavailable, match="provider"):
        to_minor_units(Decimal("10"), "usd", provider)


@pytest.mark.parametrize("currency", [None, [], {}, 123, True, "xyz", "", " usd", "USD "])
def test_unknown_or_malformed_currency_has_no_default(currency):
    with pytest.raises(PaymentsUnavailable, match="currency"):
        normalize_currency(currency)
    for provider in CATALOGUES:
        with pytest.raises(PaymentsUnavailable, match="currency"):
            to_minor_units(Decimal("10"), currency, provider)


@pytest.mark.parametrize("provider,currency,amount,expected", [
    ("stripe", "mga", "10", 10), ("razorpay", "mga", "10.29", 1029),
    ("stripe", "isk", "10", 1000), ("razorpay", "isk", "10", 10),
    ("stripe", "ugx", "10", 1000), ("razorpay", "ugx", "10", 10),
    ("stripe", "huf", "1.23", 123), ("stripe", "twd", "1.23", 123),
    ("razorpay", "huf", "1.23", 123), ("razorpay", "twd", "1.23", 123),
    ("stripe", "afn", "1.23", 123), ("razorpay", "iqd", "1.23", 1230),
])
def test_provider_differences_and_charge_not_payout_rules(provider, currency, amount, expected):
    assert to_minor_units(Decimal(amount), currency, provider) == expected


@pytest.mark.parametrize("provider,currency", [
    (p, c) for p, codes in CATALOGUES.items()
    for c, rule in codes.items() if rule["factor"] == 1000
])
def test_three_decimal_money_and_fees_respect_local_two_decimal_ledger(provider, currency):
    assert to_minor_units(Decimal("1.23"), currency, provider) == 1230
    assert to_minor_units(Decimal("1.230"), currency, provider) == 1230
    with pytest.raises(PaymentsUnavailable, match="precision"):
        to_minor_units(Decimal("1.234"), currency, provider)
    # Quantum 10 is application policy; it is not a universal Stripe API limitation.
    for bps, expected in ((0, 0), (5000, 620), (10000, 1230), (25000, 1230)):
        fee = application_fee_amount(Decimal("1.23"), bps, currency, provider)
        assert fee == expected
        assert fee % 10 == 0
        assert 0 <= fee <= 1230
    payment = SimpleNamespace(amount=Decimal("1.23"), currency=currency,
                              provider=provider, stripe_application_fee_amount=615)
    before = vars(payment).copy()
    with pytest.raises(PaymentsUnavailable, match="stored payment fee"):
        validate_payment_amount(payment)
    assert vars(payment) == before
