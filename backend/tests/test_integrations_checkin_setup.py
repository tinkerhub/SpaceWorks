"""Telegram + email setup on the production (check-in) module set.

Tinkerspace Kochi runs telegram and email ON and slack/mattermost/discord, mobile,
events, bookings, membership, member_accounts and payments OFF. These tests pin that a
Space Manager can set Telegram up end to end there (save, test, readable failures, the
alert for a new request actually reaching Telegram, rooms, health) and that the settings
surfaces offer nothing from an OFF module.
"""

import io
import json
from contextlib import nullcontext
from unittest.mock import Mock
from urllib import error as urllib_error

import pytest
from django.core import mail

from apps.accounts.models import User
from apps.hardware_requests import notifications
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.integrations.models import (
    EmailLog,
    NotificationDeliveryLog,
    NotificationDeliveryStatus,
    NotificationDestination,
)
from apps.makerspaces.module_registry import core_module_keys
from tests.return_helpers import authenticated_client, make_member, make_product, make_space

pytestmark = pytest.mark.django_db

ON = {
    "guest_handover", "printing", "telegram", "bulk_import", "containers",
    "stock_transfers", "stocktake", "reports", "qr_print_batches", "asset_units",
    "procurement", "machines", "machine_service", "maintenance", "notifications", "email",
}
TOKEN = "123456789:AAEhBOweik9ai2o4kNN-bVYeLnS-ZnXxyzQ"
CHAT = "-1001234567890"


def prod_space(slug):
    space = make_space(slug)
    space.enabled_modules = sorted(set(core_module_keys()) | ON)
    space.enabled_features = []
    space.save()
    return space


def settings_url(space):
    return f"/api/v1/admin/makerspace/{space.id}/api-settings"


def configure(space):
    space.telegram_group_chat_id = CHAT
    space.set_telegram_bot_token(TOKEN)
    space.save()


def http_error(code, description):
    body = io.BytesIO(json.dumps({"ok": False, "error_code": code, "description": description}).encode())
    return urllib_error.HTTPError("https://api.telegram.org/bot***/sendMessage", code, description, {}, body)


def send_test_alert(client, space):
    return client.post(
        "/api/v1/integrations/telegram/test-alert",
        {"makerspace_id": space.id, "message": "Test"},
        format="json",
    )


# --- save -------------------------------------------------------------------------


def test_space_manager_saves_telegram_settings_encrypted():
    space = prod_space("tg-save")
    client = authenticated_client(make_member("tg-save-mgr", space))

    response = client.patch(
        settings_url(space),
        {"telegram_group_chat_id": f" {CHAT} ", "telegram_bot_token": TOKEN},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["telegram_bot_token_set"] is True
    assert response.data["telegram_group_chat_id"] == CHAT
    space.refresh_from_db()
    assert space.telegram_bot_token.startswith("fernet:")
    assert space.get_telegram_bot_token() == TOKEN


@pytest.mark.parametrize(
    ("payload", "field", "fragment"),
    [
        ({"telegram_bot_token": "not-a-token"}, "telegram_bot_token", "BotFather"),
        ({"telegram_bot_token": "1234:abc/../../x"}, "telegram_bot_token", "BotFather"),
        ({"telegram_bot_token": "x" * 120}, "telegram_bot_token", "BotFather"),
        ({"telegram_group_chat_id": "my group"}, "telegram_group_chat_id", "chat ID"),
    ],
)
def test_malformed_telegram_values_are_refused_readably(payload, field, fragment):
    space = prod_space(f"tg-bad-{field}-{len(str(payload))}")
    client = authenticated_client(make_member(f"tg-bad-mgr-{field}-{len(str(payload))}", space))

    response = client.patch(settings_url(space), payload, format="json")

    assert response.status_code == 400
    assert fragment in str(response.data[field][0])
    space.refresh_from_db()
    assert space.telegram_bot_token == "" and space.telegram_group_chat_id == ""


def test_saving_a_secret_without_an_encryption_key_is_a_readable_503(settings):
    space = prod_space("tg-nokey")
    client = authenticated_client(make_member("tg-nokey-mgr", space))
    settings.API_CLIENT_ENC_KEY = ""

    response = client.patch(settings_url(space), {"telegram_bot_token": TOKEN}, format="json")

    assert response.status_code == 503
    assert "API_CLIENT_ENC_KEY" in response.data["detail"]
    # Clearing stores nothing encrypted, so it still works without the key.
    cleared = client.patch(settings_url(space), {"telegram_bot_token": ""}, format="json")
    assert cleared.status_code == 200


def test_makerspace_patch_applies_the_same_telegram_validation():
    space = prod_space("tg-ms-patch")
    client = authenticated_client(make_member("tg-ms-patch-mgr", space))

    response = client.patch(
        f"/api/v1/admin/makerspaces/{space.id}",
        {"telegram_group_chat_id": "nope nope"},
        format="json",
    )

    assert response.status_code == 400
    assert "telegram_group_chat_id" in response.data


# --- test alert -------------------------------------------------------------------


def test_test_alert_delivers_with_the_saved_token(monkeypatch):
    space = prod_space("tg-test-ok")
    configure(space)
    client = authenticated_client(make_member("tg-test-ok-mgr", space))
    posted = Mock(return_value=nullcontext(type("R", (), {"status": 200})()))
    monkeypatch.setattr("urllib.request.urlopen", posted)

    response = send_test_alert(client, space)

    assert response.status_code == 200
    assert response.data == {"delivered": True}
    request = posted.call_args.args[0]
    assert request.full_url.endswith(f"/bot{TOKEN}/sendMessage")
    assert json.loads(request.data)["chat_id"] == CHAT


@pytest.mark.parametrize(
    ("raised", "reason", "fragment"),
    [
        (lambda: http_error(401, "Unauthorized"), "bad_token", "BotFather"),
        (lambda: http_error(404, "Not Found"), "bad_token", "BotFather"),
        (lambda: http_error(400, "Bad Request: chat not found"), "chat_not_found", "chat ID"),
        (lambda: http_error(403, "Forbidden: bot is not a member of the supergroup chat"), "not_in_chat", "Add the bot"),
        (lambda: http_error(429, "Too Many Requests: retry after 5"), "rate_limited", "Wait a minute"),
        (lambda: urllib_error.URLError("Name or service not known"), "unreachable", "Couldn't reach Telegram"),
        (lambda: TimeoutError("timed out"), "unreachable", "Couldn't reach Telegram"),
    ],
)
def test_test_alert_failure_is_a_readable_reason_never_a_500(monkeypatch, raised, reason, fragment):
    space = prod_space(f"tg-fail-{reason}-{fragment[:4].strip()}")
    configure(space)
    client = authenticated_client(make_member(f"tg-fail-mgr-{reason}-{fragment[:4].strip()}", space))

    def fail(*_args, **_kwargs):
        raise raised()

    monkeypatch.setattr("urllib.request.urlopen", fail)

    response = send_test_alert(client, space)

    assert response.status_code == 200
    assert response.data["delivered"] is False
    assert response.data["reason"] == reason
    assert fragment in response.data["detail"]
    assert TOKEN not in response.data["detail"]


def test_test_alert_with_an_unreadable_token_is_readable(settings):
    space = prod_space("tg-unreadable")
    configure(space)
    client = authenticated_client(make_member("tg-unreadable-mgr", space))
    settings.API_CLIENT_ENC_KEY = ""

    response = send_test_alert(client, space)

    assert response.status_code == 200
    assert response.data["reason"] == "token_unreadable"


def test_test_alert_unconfigured_says_so():
    space = prod_space("tg-unconfigured")
    client = authenticated_client(make_member("tg-unconfigured-mgr", space))

    response = send_test_alert(client, space)

    assert response.data == {
        "delivered": False,
        "reason": "not_configured",
        "detail": "Telegram isn't configured yet. Save a bot token and group chat ID first.",
    }


# --- the request alert ------------------------------------------------------------


def _submitted_request(space, suffix):
    requester = User.objects.create_user(
        username=f"walkin-{suffix}", role=User.Role.REQUESTER, access_status=User.AccessStatus.ACTIVE
    )
    request = HardwareRequest.objects.create(
        makerspace=space,
        requester=requester,
        requester_username=requester.username,
        requested_for="Line follower",
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    HardwareRequestItem.objects.create(request=request, product=make_product(space, name="Arduino Uno"), requested_quantity=2)
    return request


def test_request_submitted_alert_reaches_telegram_on_the_prod_module_set(
    monkeypatch, django_capture_on_commit_callbacks
):
    space = prod_space("tg-e2e")
    configure(space)
    request = _submitted_request(space, "e2e")
    posted = Mock(return_value=nullcontext(type("R", (), {"status": 200})()))
    monkeypatch.setattr("urllib.request.urlopen", posted)

    with django_capture_on_commit_callbacks(execute=True):
        notifications.notify_request_submitted(request)

    posted.assert_called_once()
    sent = posted.call_args.args[0]
    assert sent.full_url.endswith(f"/bot{TOKEN}/sendMessage")
    body = json.loads(sent.data)
    assert body["chat_id"] == CHAT
    assert "Arduino Uno: 2" in body["text"]
    assert "reply_markup" not in body
    logs = NotificationDeliveryLog.objects.filter(makerspace=space)
    assert [(log.channel, log.status) for log in logs] == [("telegram", NotificationDeliveryStatus.SENT)]


def test_request_alert_goes_to_a_telegram_room_when_one_exists(
    monkeypatch, django_capture_on_commit_callbacks
):
    space = prod_space("tg-room")
    configure(space)
    client = authenticated_client(make_member("tg-room-mgr", space))
    created = client.post(
        f"/api/v1/admin/makerspace/{space.id}/notification-destinations",
        {"channel": "telegram", "label": "Front desk", "telegram_chat_id": "-100777"},
        format="json",
    )
    assert created.status_code == 201, created.data
    request = _submitted_request(space, "room")
    posted = Mock(return_value=nullcontext(type("R", (), {"status": 200})()))
    monkeypatch.setattr("urllib.request.urlopen", posted)

    with django_capture_on_commit_callbacks(execute=True):
        notifications.notify_request_submitted(request)

    assert json.loads(posted.call_args.args[0].data)["chat_id"] == "-100777"
    log = NotificationDeliveryLog.objects.get(makerspace=space)
    assert log.destination_label == "Front desk" and log.status == NotificationDeliveryStatus.SENT


def test_room_chat_id_is_validated():
    space = prod_space("tg-room-bad")
    client = authenticated_client(make_member("tg-room-bad-mgr", space))

    response = client.post(
        f"/api/v1/admin/makerspace/{space.id}/notification-destinations",
        {"channel": "telegram", "label": "Desk", "telegram_chat_id": "front desk"},
        format="json",
    )

    assert response.status_code == 400
    assert NotificationDestination.objects.filter(makerspace=space).count() == 0


# --- health -----------------------------------------------------------------------


def health(client, space):
    return client.get(f"/api/v1/admin/makerspace/{space.id}/integration-health").data["telegram"]


def test_health_warns_when_telegram_is_on_but_not_configured():
    space = prod_space("tg-health-unset")
    client = authenticated_client(make_member("tg-health-unset-mgr", space))

    section = health(client, space)

    assert section["enabled"] is True and section["configured"] is False
    assert section["status"] == "warn"


def test_health_reports_the_last_failure_reason_then_recovers(monkeypatch, django_capture_on_commit_callbacks):
    space = prod_space("tg-health-fail")
    configure(space)
    client = authenticated_client(make_member("tg-health-fail-mgr", space))

    def unauthorized(*_a, **_k):
        raise http_error(401, "Unauthorized")

    monkeypatch.setattr("urllib.request.urlopen", unauthorized)
    with django_capture_on_commit_callbacks(execute=True):
        notifications.notify_request_submitted(_submitted_request(space, "hf1"))

    failed = health(client, space)
    log = NotificationDeliveryLog.objects.get(makerspace=space)
    # A bad token fails the same way every time, so it is not retried.
    assert (log.status, log.attempts) == (NotificationDeliveryStatus.FAILED, 1)
    assert log.error.endswith(":bad_token")
    assert failed["status"] == "warn"
    assert "BotFather" in failed["last_failure"]["detail"]

    monkeypatch.setattr(
        "urllib.request.urlopen", Mock(return_value=nullcontext(type("R", (), {"status": 200})()))
    )
    with django_capture_on_commit_callbacks(execute=True):
        notifications.notify_request_submitted(_submitted_request(space, "hf2"))

    recovered = health(client, space)
    assert recovered["status"] == "ok"
    assert recovered["last_failure"] is None and recovered["last_sent_at"]


def test_health_is_quiet_when_the_telegram_module_is_off():
    space = prod_space("tg-health-off")
    space.enabled_modules = [key for key in space.enabled_modules if key != "telegram"]
    space.save()
    client = authenticated_client(make_member("tg-health-off-mgr", space))

    section = health(client, space)

    assert section["enabled"] is False and section["status"] == "ok"


# --- rules catalog and templates: only ON modules ---------------------------------


def test_rules_matrix_offers_only_on_module_features_and_channels():
    space = prod_space("rules-prod")
    client = authenticated_client(make_member("rules-prod-mgr", space))

    body = client.get(f"/api/v1/admin/makerspace/{space.id}/notification-rules").data

    assert [c["key"] for c in body["channels"]] == ["email", "telegram"]
    assert {f["key"] for f in body["features"]} == {"hardware_requests", "printing", "maintenance", "machine_service"}
    assert {entry["stream"] for entry in body["catalog"]} == {"hardware", "printing"}
    assert {cell["channel"] for cell in body["preferences"]} == {"email", "telegram"}
    refused = client.patch(
        f"/api/v1/admin/makerspace/{space.id}/notification-rules",
        {"preferences": [{"feature": "hardware_requests", "channel": "native_push", "enabled": True}]},
        format="json",
    )
    assert refused.status_code == 400


def test_native_push_column_appears_only_with_the_mobile_push_feature():
    space = prod_space("rules-push")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"mobile"})
    space.enabled_features = ["mobile.push"]
    space.save()
    client = authenticated_client(make_member("rules-push-mgr", space))

    body = client.get(f"/api/v1/admin/makerspace/{space.id}/notification-rules").data

    assert "native_push" in [c["key"] for c in body["channels"]]


def test_email_templates_list_only_on_module_streams():
    space = prod_space("templates-prod")
    client = authenticated_client(make_member("templates-prod-mgr", space))

    listed = client.get(f"/api/v1/admin/makerspace/{space.id}/email-templates")

    assert listed.status_code == 200
    assert {row["stream"] for row in listed.data} == {"hardware", "printing", "maintenance"}


# --- email test send --------------------------------------------------------------


def email_test(client, space):
    return client.post(f"/api/v1/admin/makerspace/{space.id}/email-test", format="json")


def test_email_test_sends_to_the_signed_in_manager_and_is_logged(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    space = prod_space("email-test-ok")
    manager = make_member("email-test-ok-mgr", space)

    response = email_test(authenticated_client(manager), space)

    assert response.status_code == 200
    assert response.data["delivered"] is True and response.data["to"] == manager.email
    assert [message.to for message in mail.outbox] == [[manager.email]]
    log = EmailLog.objects.get(pk=response.data["email_log_id"])
    assert (log.status, log.stream, log.event) == (EmailLog.Status.SENT, "test", "test_email")


def test_email_test_failure_names_the_problem(monkeypatch):
    import smtplib

    space = prod_space("email-test-fail")
    manager = make_member("email-test-fail-mgr", space)

    def broken_connection(_makerspace):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr("apps.integrations.email.makerspace_mail_connection", broken_connection)

    response = email_test(authenticated_client(manager), space)

    assert response.status_code == 200
    assert response.data["delivered"] is False
    assert "username or password" in response.data["detail"]


def test_email_test_refused_without_module_or_address_or_scope():
    space = prod_space("email-test-guard")
    other = prod_space("email-test-other")
    manager = make_member("email-test-guard-mgr", space)

    assert email_test(authenticated_client(make_member("email-test-outsider", other)), space).status_code == 404
    manager.email = ""
    manager.save(update_fields=["email"])
    assert email_test(authenticated_client(manager), space).status_code == 400
    space.enabled_modules = [key for key in space.enabled_modules if key != "email"]
    space.save()
    manager.email = "back@e.com"
    manager.save(update_fields=["email"])
    assert email_test(authenticated_client(manager), space).status_code == 400


@pytest.mark.parametrize(
    ("error", "retried"),
    [
        ("notification_delivery_failed:TelegramDeliveryError:bad_token", False),
        ("notification_delivery_failed:TelegramDeliveryError:chat_not_found", False),
        ("notification_delivery_failed:TelegramDeliveryError:not_in_chat", False),
        ("notification_delivery_failed:TelegramDeliveryError:unreachable", True),
        ("notification_delivery_failed:TelegramDeliveryError:rate_limited", True),
        ("notification_delivery_failed:ConnectionError", True),
    ],
)
def test_only_transient_telegram_failures_are_retried(error, retried):
    from apps.integrations.tasks import _should_retry_notification

    log = NotificationDeliveryLog(status=NotificationDeliveryStatus.FAILED, error=error)
    assert _should_retry_notification(log) is retried
