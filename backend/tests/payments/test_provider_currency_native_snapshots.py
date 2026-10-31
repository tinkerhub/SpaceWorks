"""Native SDK units and Connect fee snapshots through real financial services."""

from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.payments.models import MakerspacePaymentSettings, Payment, PlatformStripeConnectSettings
from apps.payments.services import create_checkout_url, create_payment
from apps.payments.services_mobile import create_mobile_intent
from apps.payments.stripe_client import PaymentsUnavailable
from tests.payments.provider_currency_flow_helpers import (
    allow_result, assert_no_external_calls, configured_machine, external_transports,
    financial_snapshot, patch_currency,
)
from tests.payments.test_currency_unit_fix_checkout import currency_payment_context

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("currency", ["SAR", "BDT"])
def test_native_currency_snapshot_sends_exact_units_then_retrieves_existing_intent(
    settings, external_transports, currency,
):
    row, manager, merchant, client = configured_machine(settings, "stripe", currency)
    # A new subject/payment with no hosted checkout; use the persisted configuration.
    payment = create_payment(
        makerspace=row.makerspace, subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=row.pk, member=manager, created_by=manager,
        amount=Decimal("10.29"), currency=merchant.default_currency,
    )
    snapshot = financial_snapshot(payment)
    patch_currency(client, merchant, "USD")
    assert_no_external_calls(external_transports)
    intent = {"id": "pi_configured_currency", "client_secret": "pi_configured_secret"}
    allow_result(external_transports.intent_create, intent)
    allow_result(external_transports.intent_retrieve, intent)
    first = create_mobile_intent(payment.pk, actor=manager)
    patch_currency(client, merchant, "EUR")
    second = create_mobile_intent(payment.pk, actor=manager)
    assert first == second == {
        "payment_id": payment.pk, "client_secret": "pi_configured_secret",
        "publishable_key": "pk_configured_currency",
    }
    create = external_transports.intent_create
    create.assert_called_once()
    assert create.call_args.args == ()
    params = create.call_args.kwargs["params"]
    assert params["amount"] == 1029
    assert type(params["amount"]) is int
    assert params["currency"] == currency.lower()
    assert params["metadata"]["payment_id"] == str(payment.pk)
    assert create.call_args.kwargs["options"] == {
        "idempotency_key": f"payment-mobile-intent-{payment.pk}",
    }
    external_transports.intent_retrieve.assert_called_once_with("pi_configured_currency")
    assert external_transports.client_factory.call_count == 2
    for call in external_transports.client_factory.call_args_list:
        assert call.kwargs == {"api_key": "sk_test_secret"}
    external_transports.checkout_create.assert_not_called()
    external_transports.account_retrieve.assert_not_called()
    external_transports.razorpay_request.assert_not_called()
    payment.refresh_from_db()
    assert financial_snapshot(payment) == snapshot
    assert (payment.amount, payment.currency) == (Decimal("10.29"), currency.lower())
    assert payment.online_rail == Payment.OnlineRail.NATIVE_PAYMENT_INTENT
    assert payment.stripe_payment_intent_id == "pi_configured_currency"
    assert payment.checkout_url == ""
    assert Payment.objects.count() == 1
    assert AuditLog.objects.filter(action="payment.created", target_id=str(payment.pk)).count() == 1
    assert AuditLog.objects.filter(
        action="payment.mobile_intent_created", target_id=str(payment.pk),
    ).count() == 1
    assert not AuditLog.objects.filter(action="payment.checkout_created").exists()


def test_connect_kwd_uses_real_account_refresh_and_ledger_quantized_fee(
    settings, external_transports,
):
    kwargs, merchant = currency_payment_context(settings, connect=True)
    platform = PlatformStripeConnectSettings.load()
    platform.application_fee_bps = 5000
    platform.save()
    payment = create_payment(**kwargs, amount=Decimal("1.23"), currency="kwd")
    assert payment.stripe_application_fee_amount == 620
    snapshot = financial_snapshot(payment)
    old_refresh = merchant.connect_status_updated_at
    allow_result(external_transports.account_retrieve, {
        "id": "acct_currency", "charges_enabled": True,
        "payouts_enabled": True, "details_submitted": True,
    })
    url = "https://checkout.example.test/connect-kwd"
    allow_result(external_transports.checkout_create, {"id": "cs_connect_kwd", "url": url})
    assert create_checkout_url(payment.pk) == url
    assert create_checkout_url(payment.pk) == url
    external_transports.account_retrieve.assert_called_once_with("acct_currency")
    merchant.refresh_from_db()
    assert merchant.connect_status == MakerspacePaymentSettings.ConnectStatus.ACTIVE
    assert merchant.connect_charges_enabled and merchant.connect_payouts_enabled
    assert merchant.connect_status_updated_at != old_refresh
    create = external_transports.checkout_create
    create.assert_called_once()
    params = create.call_args.kwargs["params"]
    price = params["line_items"][0]["price_data"]
    assert price["currency"] == "kwd"
    assert price["unit_amount"] == 1230
    assert type(price["unit_amount"]) is int
    assert params["payment_intent_data"]["application_fee_amount"] == 620
    assert create.call_args.kwargs["options"] == {
        "stripe_account": "acct_currency",
        "idempotency_key": f"payment-checkout-{payment.pk}-0",
    }
    assert external_transports.client_factory.call_count == 2
    for call in external_transports.client_factory.call_args_list:
        assert call.kwargs == {"api_key": "sk_platform"}
    external_transports.intent_create.assert_not_called()
    external_transports.intent_retrieve.assert_not_called()
    external_transports.razorpay_request.assert_not_called()
    payment.refresh_from_db()
    assert financial_snapshot(payment) == snapshot
    assert AuditLog.objects.filter(action="payment.checkout_created", target_id=str(payment.pk)).count() == 1


@pytest.mark.parametrize("rail,existing_intent", [
    ("checkout", None), ("native", None), ("native", "pi_legacy_kwd"),
])
def test_invalid_legacy_kwd_fee_is_unchanged_and_refused_before_any_account_or_sdk_io(
    settings, external_transports, rail, existing_intent,
):
    kwargs, merchant = currency_payment_context(settings, connect=True)
    # Historical insertion only: never rewrite the financial fields of an ordinary charge.
    payment = Payment.objects.create(
        **kwargs, amount=Decimal("1.23"), currency="kwd",
        stripe_provider=Payment.StripeProvider.CONNECT,
        stripe_connected_account_id="acct_currency", stripe_application_fee_amount=615,
        online_rail=Payment.OnlineRail.NATIVE_PAYMENT_INTENT if existing_intent else None,
        stripe_payment_intent_id=existing_intent,
    )
    before = Payment.objects.filter(pk=payment.pk).values().get()
    merchant_before = MakerspacePaymentSettings.objects.filter(pk=merchant.pk).values().get()
    audit_count = AuditLog.objects.count()
    with pytest.raises(PaymentsUnavailable, match="stored payment fee"):
        if rail == "checkout":
            create_checkout_url(payment.pk)
        else:
            create_mobile_intent(payment.pk, actor=kwargs["member"])
    assert_no_external_calls(external_transports)
    assert Payment.objects.filter(pk=payment.pk).values().get() == before
    assert MakerspacePaymentSettings.objects.filter(pk=merchant.pk).values().get() == merchant_before
    assert AuditLog.objects.count() == audit_count
