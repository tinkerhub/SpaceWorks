"""Shared real settings setup and strict external-only payment transports."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.test import APIClient

from apps.machines.models import MakerspaceMachineTypePricing
from apps.payments import stripe_client
from apps.payments.providers.razorpay import RazorpayProvider
from tests.payments.test_machine_payments import service_request
from tests.payments.test_models import configured_settings
from tests.payments.test_razorpay_provider import configure_razorpay
from tests.return_helpers import make_member, make_space


@pytest.fixture
def external_transports(monkeypatch):
    """Keep SDK wrappers, source resolution, adapters and Connect refresh real."""
    calls = SimpleNamespace()
    for name in ("checkout_create", "intent_create", "intent_retrieve",
                 "account_retrieve", "razorpay_request"):
        setattr(calls, name, Mock(side_effect=AssertionError(f"Unexpected external {name}")))
    # SimpleNamespace refuses all methods except those explicitly listed here.
    client = SimpleNamespace(v1=SimpleNamespace(
        checkout=SimpleNamespace(sessions=SimpleNamespace(create=calls.checkout_create)),
        payment_intents=SimpleNamespace(create=calls.intent_create, retrieve=calls.intent_retrieve),
        accounts=SimpleNamespace(retrieve=calls.account_retrieve),
    ))
    calls.client_factory = Mock(return_value=client)
    module = SimpleNamespace(StripeClient=calls.client_factory)
    monkeypatch.setattr(stripe_client, "_stripe_module", lambda: module)

    def request(self, source, method, path, body=None):
        # The real Razorpay adapter has no idempotency-header argument.
        return calls.razorpay_request(source, method, path, body)

    monkeypatch.setattr(RazorpayProvider, "_request", request)
    return calls


def assert_no_external_calls(calls):
    assert all(call.call_count == 0 for call in vars(calls).values())


def allow_result(call, result):
    call.side_effect = None
    call.return_value = result


def patch_currency(client, merchant, currency):
    response = client.patch(
        f"/api/v1/admin/makerspace/{merchant.makerspace_id}/payment-settings",
        {"default_currency": currency}, format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["default_currency"] == currency.lower()
    merchant.refresh_from_db()
    assert merchant.default_currency == currency.lower()


def configured_machine(settings, provider, currency):
    settings.PUBLIC_APP_BASE_URL = "https://app.example.test"
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    space = make_space("configured-currency-flow")
    space.enabled_features = ["payments.enabled", "payments.machines"]
    space.save(update_fields=["enabled_features", "updated_at"])
    manager = make_member("configured-currency-manager", space)
    if provider == "stripe":
        merchant = configured_settings(space)
        merchant.stripe_publishable_key = "pk_configured_currency"
        merchant.save()
    else:
        merchant = configure_razorpay(space)
    client = APIClient()
    client.force_authenticate(manager)
    patch_currency(client, merchant, currency)
    row = service_request(space, manager, config={"metering_unit": "minutes"})
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space, machine_type=row.assigned_machine.machine_type,
        rate_per_unit=Decimal("0"), flat_fee=Decimal("10.29"), payment_enabled=True,
    )
    return row, manager, merchant, client


def financial_snapshot(payment):
    return {name: getattr(payment, name) for name in (
        "amount", "currency", "provider", "stripe_provider", "stripe_connected_account_id",
        "stripe_application_fee_amount", "makerspace_id", "subject_type", "subject_id",
        "subject_label", "member_id", "created_by_id", "via_makerspace_id",
    )}
