"""Checkout boundaries must send integer currency units or refuse before I/O."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from apps.audit.models import AuditLog
from apps.payments import stripe_client
from apps.payments.models import MakerspacePaymentSettings, Payment, PlatformStripeConnectSettings
from apps.payments.providers.base import CheckoutResult
from apps.payments.services import create_checkout_url, create_payment
from tests.payments.test_machine_payments import service_request
from tests.payments.test_models import configured_settings
from tests.payments.test_razorpay_provider import configure_razorpay
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db


@pytest.fixture
def provider_calls(monkeypatch):
    calls = {}
    for name in (
        "create_checkout_session", "create_payment_intent", "retrieve_payment_intent",
        "cancel_payment_intent", "expire_checkout_session", "build_client",
    ):
        calls[name] = Mock(side_effect=AssertionError(f"Unexpected Stripe {name}"))
        monkeypatch.setattr(stripe_client, name, calls[name])
    for module in ("services", "services_mobile"):
        name = f"{module}.refresh_connected_account"
        calls[name] = Mock(side_effect=AssertionError("Unexpected Connect refresh"))
        monkeypatch.setattr(f"apps.payments.{name}", calls[name])
    calls["provider"] = Mock(side_effect=AssertionError("Unexpected provider lookup"))
    monkeypatch.setattr("apps.payments.providers.get_provider", calls["provider"])
    return calls


def currency_payment_context(settings, *, provider="stripe", connect=False):
    settings.PUBLIC_APP_BASE_URL = "https://app.example.test"
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test" if connect else ""
    space = make_space("currency-unit-fix")
    actor = make_member("currency-unit-fix-member", space)
    if connect:
        platform = PlatformStripeConnectSettings.load()
        platform.set_stripe_secret_key("sk_platform")
        platform.set_stripe_webhook_secret("whsec_platform")
        platform.stripe_publishable_key = "pk_platform"
        platform.stripe_connect_client_id = "ca_platform"
        platform.application_fee_bps = 1250
        platform.save()
        merchant = MakerspacePaymentSettings.objects.create(
            makerspace=space, connect_account_id="acct_currency",
            connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
            connect_charges_enabled=True,
        )
    elif provider == "razorpay":
        merchant = configure_razorpay(space)
    else:
        merchant = configured_settings(space)
        merchant.stripe_publishable_key = "pk_currency"
        merchant.save()
    subject = service_request(space, actor)
    kwargs = dict(
        makerspace=space, member=actor, created_by=actor,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST, subject_id=subject.pk,
    )
    return kwargs, merchant


@pytest.mark.parametrize("currency,amount", [
    pytest.param("xyz", "10", id="unknown"),
    pytest.param("kwd", "10.001", id="three-decimal-overprecision"),
    pytest.param("jpy", "10.01", id="zero-fraction"),
    pytest.param("isk", "10.01", id="special-fraction"),
    pytest.param("usd", "10.001", id="overprecision"),
])
def test_invalid_new_charge_creates_neither_payment_nor_audit(
    settings, provider_calls, currency, amount,
):
    kwargs, _ = currency_payment_context(settings)
    before = AuditLog.objects.count()
    with pytest.raises(stripe_client.PaymentsUnavailable):
        create_payment(**kwargs, currency=currency, amount=Decimal(amount))
    assert not Payment.objects.exists()
    assert AuditLog.objects.count() == before
    assert all(mock.call_count == 0 for mock in provider_calls.values())


@pytest.mark.parametrize("provider,currency,amount,expected", [
    pytest.param("stripe", "jpy", "10", 10, id="stripe-jpy"),
    pytest.param("razorpay", "jpy", "10", 10, id="razorpay-jpy"),
    pytest.param("stripe", "usd", "10.29", 1029, id="stripe-usd"),
    pytest.param("razorpay", "inr", "10.29", 1029, id="razorpay-inr"),
])
def test_checkout_sends_exact_units_and_reuses_the_created_link(
    settings, provider_calls, provider, currency, amount, expected,
):
    kwargs, _ = currency_payment_context(settings, provider=provider)
    payment = create_payment(**kwargs, currency=currency, amount=Decimal(amount))
    url = "https://checkout.example.test/currency"
    if provider == "stripe":
        sender = provider_calls["create_checkout_session"]
        sender.side_effect = None
        sender.return_value = {"id": "cs_currency", "url": url}
    else:
        seam = Mock()
        seam.create_checkout.return_value = CheckoutResult("plink_currency", url)
        provider_calls["provider"].side_effect = None
        provider_calls["provider"].return_value = seam
        sender = seam.create_checkout

    assert create_checkout_url(payment.pk) == url
    assert create_checkout_url(payment.pk) == url
    sender.assert_called_once()
    if provider == "stripe":
        params = sender.call_args.kwargs
        price = params["line_items"][0]["price_data"]
        assert price["unit_amount"] == expected
        assert type(price["unit_amount"]) is int
        assert price["currency"] == currency
        assert params["idempotency_key"] == f"payment-checkout-{payment.pk}-0"
    else:
        request = sender.call_args.args[1]
        assert request.amount_minor == expected
        assert type(request.amount_minor) is int
        assert request.currency == currency
        assert request.idempotency_key == f"payment-checkout-{payment.pk}-0"
    payment.refresh_from_db()
    assert payment.checkout_url == url
    assert payment.online_rail == Payment.OnlineRail.CHECKOUT


def test_connect_jpy_checkout_snapshots_a_fee_bounded_by_the_charge(settings, provider_calls):
    kwargs, merchant = currency_payment_context(settings, connect=True)
    payment = create_payment(**kwargs, amount=Decimal("10"), currency="jpy")
    refresh = provider_calls["services.refresh_connected_account"]
    refresh.side_effect = None
    refresh.return_value = merchant
    sender = provider_calls["create_checkout_session"]
    sender.side_effect = None
    sender.return_value = {"id": "cs_connect_jpy", "url": "https://checkout.example.test/jpy"}

    create_checkout_url(payment.pk)

    params = sender.call_args.kwargs
    charge = params["line_items"][0]["price_data"]["unit_amount"]
    assert charge == 10
    assert payment.stripe_application_fee_amount == 1
    assert params["payment_intent_data"]["application_fee_amount"] == 1 <= charge
    assert sender.call_args.args[0].connected_account_id == "acct_currency"


@pytest.mark.parametrize("currency,fee", [
    pytest.param("jpy", 11, id="fee-exceeds-charge"),
    pytest.param("isk", 1, id="special-fee-fraction"),
])
def test_legacy_invalid_checkout_fee_is_refused_before_connect_refresh(
    settings, provider_calls, currency, fee,
):
    kwargs, _ = currency_payment_context(settings, connect=True)
    # Insert a historical row directly: the new-charge service would refuse this fee.
    payment = Payment.objects.create(
        **kwargs, amount=Decimal("10"), currency=currency,
        stripe_provider="connect", stripe_connected_account_id="acct_currency",
        stripe_application_fee_amount=fee,
    )
    before = AuditLog.objects.count()
    with pytest.raises(stripe_client.PaymentsUnavailable, match="stored payment fee"):
        create_checkout_url(payment.pk)
    assert all(mock.call_count == 0 for mock in provider_calls.values())
    payment.refresh_from_db()
    assert payment.online_rail is None
    assert payment.checkout_url == ""
    assert AuditLog.objects.count() == before
