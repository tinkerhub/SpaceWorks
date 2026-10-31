"""Native payment validation and retained/offline ledger compatibility."""

from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.payments.models import Payment
from apps.payments.offline_payments import create_offline_payment
from apps.payments.services import create_checkout_url, create_payment, mark_offline
from apps.payments.services_mobile import create_mobile_intent
from apps.payments.stripe_client import PaymentsUnavailable
from tests.payments.test_currency_unit_fix_checkout import (
    currency_payment_context,
    provider_calls,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("currency,amount,expected", [
    pytest.param("jpy", "10", 10, id="jpy"),
    pytest.param("usd", "10.29", 1029, id="usd"),
    pytest.param("inr", "10.29", 1029, id="inr"),
])
def test_native_intent_sends_exact_units_and_retrieves_existing_intent(
    settings, provider_calls, currency, amount, expected,
):
    kwargs, _ = currency_payment_context(settings)
    payment = create_payment(**kwargs, currency=currency, amount=Decimal(amount))
    intent = {"id": "pi_currency", "client_secret": "pi_currency_secret"}
    create = provider_calls["create_payment_intent"]
    retrieve = provider_calls["retrieve_payment_intent"]
    for call in (create, retrieve):
        call.side_effect = None
        call.return_value = intent

    first = create_mobile_intent(payment.pk, actor=kwargs["member"])
    second = create_mobile_intent(payment.pk, actor=kwargs["member"])

    assert first == second == {
        "payment_id": payment.pk, "client_secret": "pi_currency_secret",
        "publishable_key": "pk_currency",
    }
    create.assert_called_once()
    assert create.call_args.kwargs["amount"] == expected
    assert type(create.call_args.kwargs["amount"]) is int
    assert create.call_args.kwargs["currency"] == currency
    assert create.call_args.kwargs["idempotency_key"] == f"payment-mobile-intent-{payment.pk}"
    retrieve.assert_called_once()
    assert retrieve.call_args.args[1] == "pi_currency"
    payment.refresh_from_db()
    assert payment.online_rail == Payment.OnlineRail.NATIVE_PAYMENT_INTENT
    assert payment.stripe_payment_intent_id == "pi_currency"
    assert AuditLog.objects.filter(
        action="payment.mobile_intent_created", target_id=str(payment.pk),
    ).count() == 1


@pytest.mark.parametrize("existing_intent", [False, True], ids=["new", "existing"])
def test_invalid_legacy_native_fee_precedes_refresh_create_and_retrieve(
    settings, provider_calls, existing_intent,
):
    kwargs, _ = currency_payment_context(settings, connect=True)
    payment = Payment.objects.create(
        **kwargs, amount=Decimal("10"), currency="jpy",
        stripe_provider="connect", stripe_connected_account_id="acct_currency",
        stripe_application_fee_amount=11,
        online_rail=Payment.OnlineRail.NATIVE_PAYMENT_INTENT if existing_intent else None,
        stripe_payment_intent_id="pi_legacy" if existing_intent else None,
    )
    before = AuditLog.objects.count()

    with pytest.raises(PaymentsUnavailable, match="stored payment fee"):
        create_mobile_intent(payment.pk, actor=kwargs["member"])

    assert all(mock.call_count == 0 for mock in provider_calls.values())
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
    assert payment.stripe_payment_intent_id == ("pi_legacy" if existing_intent else None)
    assert AuditLog.objects.count() == before


def test_native_razorpay_is_refused_without_any_provider_call(settings, provider_calls):
    kwargs, _ = currency_payment_context(settings, provider="razorpay")
    payment = create_payment(**kwargs, amount=Decimal("10"), currency="jpy")
    with pytest.raises(PaymentsUnavailable, match="require Stripe"):
        create_mobile_intent(payment.pk, actor=kwargs["member"])
    assert all(mock.call_count == 0 for mock in provider_calls.values())
    payment.refresh_from_db()
    assert payment.online_rail is None
    assert payment.stripe_payment_intent_id is None


@pytest.mark.parametrize("field", ["checkout_url", "stripe_checkout_url"])
def test_existing_legacy_checkout_link_is_returned_without_new_provider_work(
    settings, provider_calls, field,
):
    kwargs, _ = currency_payment_context(settings)
    payment = Payment.objects.create(
        **kwargs, amount=Decimal("10"), currency="jpy",
        stripe_application_fee_amount=11,
        **{field: "https://checkout.example.test/retained"},
    )
    assert create_checkout_url(payment.pk) == "https://checkout.example.test/retained"
    assert all(mock.call_count == 0 for mock in provider_calls.values())


def test_manual_offline_three_decimal_currency_compatibility_remains_settleable(
    settings, provider_calls,
):
    kwargs, _ = currency_payment_context(settings)
    payment = create_offline_payment(**kwargs, amount=Decimal("10.25"), currency="kwd")
    assert payment.status == Payment.Status.PENDING
    assert payment.currency == "kwd"
    assert mark_offline(payment, kwargs["member"]).status == Payment.Status.PAID_OFFLINE
    assert create_checkout_url(payment.pk) == ""
    with pytest.raises(Payment.DoesNotExist):
        create_mobile_intent(payment.pk, actor=kwargs["member"])
    assert all(mock.call_count == 0 for mock in provider_calls.values())
    assert AuditLog.objects.filter(
        action="payment.paid_offline", target_id=str(payment.pk),
    ).count() == 1


def test_legacy_invalid_fee_can_be_reconciled_offline(settings, provider_calls):
    kwargs, _ = currency_payment_context(settings)
    payment = Payment.objects.create(
        **kwargs, amount=Decimal("10"), currency="jpy", stripe_application_fee_amount=11,
    )
    assert mark_offline(payment, kwargs["member"]).status == Payment.Status.PAID_OFFLINE
    assert create_checkout_url(payment.pk) == ""
    assert all(mock.call_count == 0 for mock in provider_calls.values())
