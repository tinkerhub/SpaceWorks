"""Real tenant API probes; replace only DNS or the email transport configuration."""

import socket

from cryptography.fernet import Fernet
from django.core import mail
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.integrations.models import EmailLog, PlatformEmailSettings
from apps.integrations.models_destinations import NotificationDestination
from apps.payments.models import MakerspacePaymentSettings, Payment, StripeConnectOAuthState


def webhook_destination(space, client, *, actor, channel, monkeypatch, settings):
    # Keep URL validation and encryption real, with no DNS or delivery traffic.
    if not settings.API_CLIENT_ENC_KEY:
        settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(
        "apps.integrations.webhook_validation.socket.getaddrinfo",
        lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port))
        ],
    )
    url = f"https://hooks.example.test/{channel}/synthetic-contract-credential"
    destinations = NotificationDestination.objects.filter(makerspace=space)
    audits = AuditLog.objects.filter(
        makerspace=space, action="notification.destination_created"
    )
    assert not destinations.exists()
    assert not audits.exists()

    response = client.post(
        reverse("admin-notification-destinations", args=[space.pk]),
        {"channel": channel, "label": "Contract room", "webhook_url": url},
        format="json",
    )
    assert "synthetic-contract-credential" not in str(response.data)

    if channel in space.enabled_modules:
        assert response.status_code == 201
        assert NotificationDestination.objects.count() == destinations.count() == 1
        destination = destinations.get(pk=response.data["id"])
        assert destination.makerspace_id == space.pk
        assert destination.channel == channel
        assert response.data["channel"] == channel
        assert destination.label == "Contract room"
        assert destination.webhook_url.startswith("fernet:")
        assert destination.get_webhook_url() == url
        assert response.data["credential_set"] is True
        assert "webhook_url" not in response.data
        assert url not in str(response.data)
        assert destination.webhook_url not in str(response.data)
        assert audits.count() == 1
        audit = audits.get()
        assert actor.is_active and actor.is_staff
        assert actor.access_status == actor.AccessStatus.ACTIVE
        assert audit.actor_id == actor.pk
        assert audit.makerspace_id == space.pk
        assert (audit.target_type, audit.target_id) == (
            "makerspaces.makerspace", str(space.pk)
        )
        # Exact metadata also prevents plaintext or encrypted credential leakage.
        assert audit.meta == {"channel": channel, "label": "Contract room"}
    else:
        assert response.status_code == 400
        assert not destinations.exists()
        assert not audits.exists()
    return response


def email_test(space, client, *, actor, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "contract-sender@example.test"
    # Both connection selectors remain real. Blank hosts avoid SMTP validation/DNS.
    assert not space.smtp_host
    platform = PlatformEmailSettings.load()
    platform.smtp_host = ""
    platform.save(update_fields=["smtp_host"])
    mail.get_connection()  # Initialize locmem's outbox without sending anything.
    assert mail.outbox == []
    logs = EmailLog.objects.filter(makerspace=space)
    audits = AuditLog.objects.filter(makerspace=space, action="email.test_sent")
    assert not logs.exists()
    assert not audits.exists()

    response = client.post(reverse("admin-email-test", args=[space.pk]), format="json")

    if "email" in space.enabled_modules:
        assert response.status_code == 200
        assert response.data["delivered"] is True
        assert set(response.data) == {"delivered", "to", "email_log_id"}
        assert EmailLog.objects.count() == logs.count() == 1
        log = logs.get(pk=response.data["email_log_id"])
        assert log.makerspace_id == space.pk
        assert log.status == EmailLog.Status.SENT
        assert (log.stream, log.event) == ("test", "test_email")
        assert log.to_email == response.data["to"]
        assert log.to_email == actor.email
        assert (log.audience, log.connection_kind) == ("staff", "makerspace")
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [log.to_email]
        message = mail.outbox[0]
        assert message.subject == log.subject == f"Test email from {space.name}"
        assert message.from_email == "contract-sender@example.test"
        assert message.body == log.text_body
        assert f"This is a test email from {space.name}." in message.body
        assert audits.count() == 1
        audit = audits.get()
        assert audit.actor_id == actor.pk
        assert audit.makerspace_id == space.pk
        assert (audit.target_type, audit.target_id) == (
            "makerspaces.makerspace", str(space.pk)
        )
        assert audit.meta == {"email_log_id": log.pk, "status": log.status}
    else:
        assert response.status_code == 400
        assert mail.outbox == []
        assert not logs.exists()
        assert not audits.exists()
    return response


def payment_settings(space, client, *, actor):
    url = reverse("admin-makerspace-payment-settings", args=[space.pk])
    rows = MakerspacePaymentSettings.objects.filter(makerspace=space)
    audits = AuditLog.objects.filter(makerspace=space, action="payments.settings_updated")
    assert not rows.exists()
    assert not audits.exists()
    assert not Payment.objects.exists()
    assert not StripeConnectOAuthState.objects.exists()

    read = client.get(url)
    if "payments" in space.enabled_modules:
        assert read.status_code == 200
        assert read.data["default_currency"] == "inr"
        # GET exposes defaults without persisting configuration or auditing a write.
        assert not rows.exists()
        assert not audits.exists()
    response = client.patch(url, {"default_currency": "eur"}, format="json")

    if "payments" in space.enabled_modules:
        assert read.status_code == 200
        assert response.status_code == 200
        assert response.data["default_currency"] == "eur"
        assert rows.get().default_currency == "eur"
        assert MakerspacePaymentSettings.objects.count() == rows.count() == 1
        saved = rows.get()
        assert saved.makerspace_id == space.pk
        reread = client.get(url)
        assert reread.status_code == 200
        assert reread.data["default_currency"] == "eur"
        assert audits.count() == 1
        audit = audits.get()
        assert audit.actor_id == actor.pk
        assert audit.makerspace_id == space.pk
        assert (audit.target_type, audit.target_id) == (
            "payments.makerspacepaymentsettings", str(saved.pk)
        )
    else:
        # Both methods must independently refuse; returning only PATCH would hide GET.
        assert read.status_code == 400
        assert "payments" in str(read.data)
        assert response.status_code == 400
        assert "payments" in str(response.data)
        assert not rows.exists()
        assert not audits.exists()
    assert not Payment.objects.exists()
    assert not StripeConnectOAuthState.objects.exists()
    return response
