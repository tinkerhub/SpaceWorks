"""D3 module gates, part 2: money, printing, chat (A5-A7, P1, C3, payments report registry)."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.module_registry import core_module_keys, with_dependencies
from apps.payments.models import MakerspacePaymentSettings, Payment, StripeConnectOAuthState
from apps.payments.offline_payments import create_offline_payment
from apps.payments.stripe_client import PaymentsUnavailable


pytestmark = pytest.mark.django_db

CORE = frozenset(core_module_keys())


def _space(slug, *extra):
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=sorted(with_dependencies(CORE | set(extra)))
    )


def _superadmin(slug):
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


# --- A5: new charges only -----------------------------------------------------------


def _membership_subject(space):
    member = User.objects.create_user(
        username=f"{space.slug}-payer", email=f"{space.slug}-payer@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    return member, MakerspaceMembership.objects.create(
        makerspace=space, user=member, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_counter_settlement_raises_no_new_charge_with_payments_off(enabled):
    space = _space(f"d3-offline-{enabled}".lower(), *(["payments"] if enabled else []))
    member, membership = _membership_subject(space)

    payment = create_offline_payment(
        makerspace=space, subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk, member=member, amount=5, currency="usd", created_by=member,
    )

    assert (payment is not None) is enabled
    assert Payment.objects.filter(makerspace=space).exists() is enabled


def test_online_charge_creation_refuses_with_payments_off_even_with_credentials():
    from apps.payments.services import create_payment

    space = _space("d3-online-off")
    settings = MakerspacePaymentSettings(makerspace=space)
    settings.set_stripe_secret_key("sk_test_d3")
    settings.set_stripe_webhook_secret("whsec_test_d3")
    settings.save()
    member, membership = _membership_subject(space)

    with pytest.raises(PaymentsUnavailable):
        create_payment(
            makerspace=space, subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
            subject_id=membership.pk, member=member, amount=5, currency="usd", created_by=member,
        )
    assert not Payment.objects.filter(makerspace=space).exists()


# --- P1: payment settings and Connect onboarding -------------------------------------


@pytest.mark.parametrize("enabled", [False, True])
def test_payment_settings_follow_the_payments_module(enabled):
    space = _space(f"d3-pay-settings-{enabled}".lower(), *(["payments"] if enabled else []))
    client = _client(_superadmin(f"d3-pay-settings-admin-{enabled}".lower()))
    url = f"/api/v1/admin/makerspace/{space.pk}/payment-settings"

    read = client.get(url)
    written = client.patch(url, {"default_currency": "eur"}, format="json")

    if enabled:
        assert (read.status_code, written.status_code) == (200, 200)
        assert MakerspacePaymentSettings.objects.get(makerspace=space).default_currency == "eur"
    else:
        assert (read.status_code, written.status_code) == (400, 400)
        assert "payments" in str(written.data["module"])
        assert not MakerspacePaymentSettings.objects.filter(makerspace=space, default_currency="eur").exists()


@pytest.mark.parametrize("enabled", [False, True])
def test_connect_onboarding_rechecks_the_module_under_the_lock(enabled, settings, monkeypatch):
    from apps.payments import connect

    settings.STRIPE_CONNECT_REDIRECT_URI = "https://example.test/callback"
    monkeypatch.setattr(
        connect.PlatformStripeConnectSettings, "load",
        classmethod(lambda cls: SimpleNamespace(is_configured=True, stripe_connect_client_id="ca_d3")),
    )
    space = _space(f"d3-connect-{enabled}".lower(), *(["payments"] if enabled else []))
    actor = _superadmin(f"d3-connect-admin-{enabled}".lower())

    if enabled:
        assert connect.create_onboarding(space, actor).startswith("https://")
        assert StripeConnectOAuthState.objects.filter(makerspace=space).count() == 1
    else:
        with pytest.raises(ValidationError):
            connect.create_onboarding(space, actor)
        assert not StripeConnectOAuthState.objects.filter(makerspace=space).exists()


# --- A6: public printer status by token -------------------------------------------


@pytest.mark.parametrize("enabled", [False, True])
def test_printer_status_by_token_is_not_found_with_printing_off(enabled):
    space = _space(f"d3-print-status-{enabled}".lower(), "machine_service", *(["printing"] if enabled else []))
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=printer_type, name="Prints")
    requester = User.objects.create_user(
        username=f"{space.slug}-requester", email=f"{space.slug}-requester@example.test"
    )
    job = MachineServiceRequest.objects.create(
        makerspace=space, queue=queue, requester=requester, requester_name="Visitor",
        title="Bracket",
    )

    response = APIClient().get(
        f"/api/v1/public/machine-service/3d-printer/requests/{job.public_token}/status"
    )

    assert response.status_code == (200 if enabled else 404)


# --- A7: printing email templates -------------------------------------------------


@pytest.mark.parametrize("enabled", [False, True])
def test_printing_email_templates_follow_the_printing_module(enabled):
    space = _space(f"d3-print-mail-{enabled}".lower(), "machine_service", *(["printing"] if enabled else []))
    client = _client(_superadmin(f"d3-print-mail-admin-{enabled}".lower()))

    rows = client.get(f"/api/v1/admin/makerspace/{space.pk}/email-templates").data

    assert any(row["stream"] == "printing" for row in rows) is enabled


# --- C3: direct Telegram sends -----------------------------------------------------


@pytest.mark.parametrize("enabled", [False, True])
def test_direct_telegram_sends_respect_the_telegram_module(enabled, monkeypatch):
    from apps.apiclients import notifications as api_notifications
    from apps.makerspaces import subdomain_notifications

    space = _space(f"d3-telegram-{enabled}".lower(), *(["telegram"] if enabled else []))
    api_send, subdomain_send = Mock(), Mock()
    monkeypatch.setattr(api_notifications, "send_message", api_send)
    monkeypatch.setattr(subdomain_notifications, "send_message", subdomain_send)

    api_notifications.notify_api_key_request_resolved(SimpleNamespace(
        pk=1, status="approved", makerspace=space, requester=None, label="App",
        resolution_note="",
    ))
    subdomain_notifications.notify_subdomain_request_resolved(SimpleNamespace(
        pk=1, status="rejected", makerspace=space, requested_by=None, requested_label="lab",
        note="", Status=SimpleNamespace(APPROVED="approved", REJECTED="rejected"),
    ))

    assert api_send.called is enabled
    assert subdomain_send.called is enabled
