"""Settings -> machine pricing -> immutable Payment -> real provider adapter."""

from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.machines import role_scope
from apps.machines.models import MachineServiceRequest
from apps.machines.service_workflow import accept, complete, start
from apps.payments.models import Payment
from apps.payments.resolution import resolve_payment_source
from apps.payments.services import create_checkout_url, create_payment
from apps.payments.stripe_client import PaymentsUnavailable
from tests.payments.provider_currency_flow_helpers import (
    allow_result, assert_no_external_calls, configured_machine, external_transports,
    financial_snapshot, patch_currency,
)
from tests.payments.test_currency_unit_fix_checkout import currency_payment_context

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
@pytest.mark.parametrize("currency", ["SAR", "BDT"])
def test_configured_currency_survives_settings_switches_before_and_after_checkout(
    settings, django_capture_on_commit_callbacks, external_transports, provider, currency,
):
    row, manager, merchant, client = configured_machine(settings, provider, currency)
    assert resolve_payment_source(row.makerspace).vendor == provider
    assert_no_external_calls(external_transports)
    # Hold the real post-commit checkout until after the default has changed.
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        accept(row, manager)
        start(row, manager, role_scope.manage_scope_for(manager, row.makerspace_id),
              machine_id=row.assigned_machine_id)
        completed = complete(row, manager, actual_minutes=1, consumptions=[])
    assert callbacks
    assert completed.status == MachineServiceRequest.Status.COMPLETED
    row.refresh_from_db()
    assert row.status == MachineServiceRequest.Status.COMPLETED
    payment = Payment.objects.get(
        makerspace=row.makerspace, subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=row.pk,
    )
    assert (payment.amount, payment.currency, payment.provider) == (
        Decimal("10.29"), currency.lower(), provider,
    )
    assert payment.member_id == manager.pk
    assert payment.stripe_provider == Payment.StripeProvider.RAW
    assert payment.stripe_connected_account_id is None
    assert payment.stripe_application_fee_amount == 0
    snapshot = financial_snapshot(payment)
    created = AuditLog.objects.get(action="payment.created", target_id=str(payment.pk))
    assert created.actor == manager
    assert created.makerspace_id == row.makerspace_id
    assert created.meta == {
        "payment_id": payment.pk, "subject_type": payment.subject_type,
        "subject_id": row.pk, "amount": "10.29", "currency": currency.lower(),
        "via_makerspace_id": None,
    }
    assert not AuditLog.objects.filter(action="payment.checkout_created").exists()
    patch_currency(client, merchant, "USD")
    payment.refresh_from_db()
    assert financial_snapshot(payment) == snapshot
    assert_no_external_calls(external_transports)

    url = "https://checkout.example.test/configured-currency"
    if provider == "stripe":
        sender = external_transports.checkout_create
        allow_result(sender, {"id": "cs_configured_currency", "url": url})
    else:
        sender = external_transports.razorpay_request
        allow_result(sender, {"id": "plink_configured_currency", "short_url": url})
    assert create_checkout_url(payment.pk, actor=manager) == url
    assert create_checkout_url(payment.pk, actor=manager) == url
    patch_currency(client, merchant, "EUR")
    assert create_checkout_url(payment.pk, actor=manager) == url
    sender.assert_called_once()
    if provider == "stripe":
        assert sender.call_args.args == ()
        params = sender.call_args.kwargs["params"]
        price = params["line_items"][0]["price_data"]
        assert price["currency"] == currency.lower()
        assert price["unit_amount"] == 1029
        assert type(price["unit_amount"]) is int
        assert params["client_reference_id"] == str(payment.pk)
        assert sender.call_args.kwargs["options"] == {
            "idempotency_key": f"payment-checkout-{payment.pk}-0",
        }
        external_transports.client_factory.assert_called_once_with(api_key="sk_test_secret")
        external_transports.razorpay_request.assert_not_called()
    else:
        source, method, path, body = sender.call_args.args
        assert (source.vendor, method, path) == ("razorpay", "POST", "/payment_links")
        assert source.publishable_key == "rzp_test_key"
        assert body["amount"] == 1029
        assert type(body["amount"]) is int
        assert body["currency"] == currency
        assert body["reference_id"] == str(payment.pk)
        assert body["notes"]["payment_id"] == str(payment.pk)
        assert sender.call_args.kwargs == {}  # No idempotency header/options on this rail.
        assert "headers" not in body and "idempotency_key" not in body
        external_transports.client_factory.assert_not_called()
        external_transports.checkout_create.assert_not_called()
    external_transports.intent_create.assert_not_called()
    external_transports.intent_retrieve.assert_not_called()
    external_transports.account_retrieve.assert_not_called()
    payment.refresh_from_db()
    assert financial_snapshot(payment) == snapshot
    assert payment.checkout_url == url
    assert payment.external_order_id == (
        "cs_configured_currency" if provider == "stripe" else "plink_configured_currency"
    )
    assert payment.online_rail == Payment.OnlineRail.CHECKOUT
    assert Payment.objects.count() == 1
    assert AuditLog.objects.filter(action="payment.created", target_id=str(payment.pk)).count() == 1
    checkout = AuditLog.objects.get(action="payment.checkout_created", target_id=str(payment.pk))
    assert checkout.actor == manager
    assert checkout.meta == {
        "payment_id": payment.pk, "provider": provider,
        "subject_type": payment.subject_type, "subject_id": row.pk,
    }


@pytest.mark.parametrize("provider,currency,amount", [
    ("stripe", "iqd", "10"), ("razorpay", "afn", "10"),
    ("stripe", "xyz", "10"), ("razorpay", "xyz", "10"),
    ("stripe", "kwd", "1.234"), ("razorpay", "kwd", "1.234"),
])
def test_invalid_new_charge_fails_before_payment_audit_or_transport(
    settings, external_transports, provider, currency, amount,
):
    kwargs, _ = currency_payment_context(settings, provider=provider)
    assert resolve_payment_source(kwargs["makerspace"]).vendor == provider
    before = AuditLog.objects.count()
    with pytest.raises(PaymentsUnavailable):
        create_payment(**kwargs, currency=currency, amount=Decimal(amount))
    assert not Payment.objects.exists()
    assert AuditLog.objects.count() == before
    assert_no_external_calls(external_transports)


@pytest.mark.parametrize("provider,currency", [("stripe", "IQD"), ("razorpay", "AFN")])
def test_unsupported_configured_currency_never_blocks_machine_completion(
    settings, django_capture_on_commit_callbacks, external_transports, provider, currency,
):
    row, manager, _, _ = configured_machine(settings, provider, currency)
    with django_capture_on_commit_callbacks(execute=False):
        accept(row, manager)
        start(row, manager, role_scope.manage_scope_for(manager, row.makerspace_id),
              machine_id=row.assigned_machine_id)
        assert complete(row, manager, actual_minutes=1, consumptions=[]).status == (
            MachineServiceRequest.Status.COMPLETED
        )
    row.refresh_from_db()
    assert row.status == MachineServiceRequest.Status.COMPLETED
    assert not Payment.objects.exists()
    assert not AuditLog.objects.filter(action="payment.created").exists()
    assert_no_external_calls(external_transports)
