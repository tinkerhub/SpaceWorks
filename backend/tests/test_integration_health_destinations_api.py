"""Destination diagnostics through the real staff API, serializer and health service."""

import json

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.integrations import health
from apps.integrations.models import NotificationDeliveryLog, NotificationDeliveryStatus
from apps.integrations.telegram_errors import DETAILS
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.module_registry import default_enabled_module_keys
from tests.return_helpers import authenticated_client, make_member, make_space
from tests.test_notification_destinations import telegram_destination, webhook_destination


pytestmark = pytest.mark.django_db


def health_url(space):
    return f"/api/v1/admin/makerspace/{space.pk}/integration-health"


def delivery(room, status, **values):
    return NotificationDeliveryLog.objects.create(
        makerspace=room.makerspace, destination=room, destination_label=room.label,
        channel=room.channel, feature="maintenance", event="logged",
        text_body="Machine needs attention", status=status, **values,
    )


def get_health(space, username="destination-health-manager"):
    manager = make_member(username, space)
    response = authenticated_client(manager).get(health_url(space))
    assert response.status_code == 200, response.data
    return response


def test_destination_health_serializes_typed_rooms_and_excludes_foreign_secrets():
    space = make_space("destination-health-typed")
    space.set_telegram_bot_token("123456:bot-secret")
    space.save(update_fields=["telegram_bot_token"])
    rooms = [
        webhook_destination(space, channel, f"{channel.title()} room", f"https://hooks.example/{channel}-secret")
        for channel in ("slack", "discord", "mattermost")
    ]
    rooms.append(telegram_destination(space, "Telegram room", "-100-chat-secret"))
    rooms[0].is_active = False
    rooms[0].save(update_fields=["is_active"])
    sent_at = timezone.now().replace(microsecond=0)
    secret_error = (
        "provider echoed https://hooks.example/webhook-secret "
        "https://api.telegram.org/bot123456:bot-secret/sendMessage -100-chat-secret"
    ) * 20
    for room in rooms:
        delivery(room, NotificationDeliveryStatus.SENT, sent_at=sent_at)
        delivery(room, NotificationDeliveryStatus.FAILED, error=secret_error)
    foreign = webhook_destination(make_space("destination-health-foreign"), "slack", "Foreign secret room")
    delivery(foreign, NotificationDeliveryStatus.FAILED, error="foreign-error-secret")

    response = get_health(space)

    section = response.data["chat_destinations"]
    assert section["status"] == "warn"
    assert section["legacy_channels"] == {}
    rows = {row["id"]: row for row in section["destinations"]}
    assert set(rows) == {room.pk for room in rooms}
    for room in rooms:
        row = rows[room.pk]
        assert set(row) == {
            "id", "channel", "label", "is_active", "configured",
            "last_sent_at", "failed", "last_failure",
        }
        assert type(row["id"]) is int and row["id"] == room.pk
        assert (row["channel"], row["label"]) == (room.channel, room.label)
        assert row["is_active"] is room.is_active
        assert row["configured"] is True
        assert type(row["failed"]) is int and row["failed"] == 1
        assert parse_datetime(row["last_sent_at"]) == sent_at
        assert parse_datetime(row["last_failure"]["at"]) is not None
        assert row["last_failure"]["error"] == (
            "The last alert wasn't delivered. Check the channel configuration."
        )
        assert len(row["last_failure"]["error"]) <= 200
    payload = json.dumps(response.data)
    for secret in (
        "webhook-secret", "bot-secret", "-100-chat-secret", "hooks.example",
        "foreign-error-secret", "Foreign secret room", "slack-secret",
        "discord-secret", "mattermost-secret", space.telegram_bot_token,
    ):
        assert secret not in payload


def test_destination_health_exposes_only_closed_telegram_reason_detail():
    space = make_space("destination-health-telegram-reason")
    room = telegram_destination(space, "Front desk")
    delivery(
        room, NotificationDeliveryStatus.FAILED,
        error="notification_delivery_failed:TelegramDeliveryError:chat_not_found",
    )

    response = get_health(space)

    row = response.data["chat_destinations"]["destinations"][0]
    assert row["last_failure"]["error"] == DETAILS["chat_not_found"]
    assert row["configured"] is False  # A chat ID alone cannot send an alert.


@pytest.mark.parametrize("bot_present", [False, True], ids=["without-bot", "with-bot"])
def test_inactive_telegram_room_remains_visible_with_accurate_configuration(bot_present):
    space = make_space("destination-health-inactive")
    if bot_present:
        space.set_telegram_bot_token("123456:inactive-bot-secret")
        space.save(update_fields=["telegram_bot_token"])
    room = telegram_destination(space, "Paused handover")
    room.is_active = False
    room.save(update_fields=["is_active"])

    row = get_health(space).data["chat_destinations"]["destinations"][0]

    assert row == {
        "id": room.pk, "channel": "telegram", "label": "Paused handover",
        "is_active": False, "configured": bot_present,
        "last_sent_at": None, "failed": 0, "last_failure": None,
    }


@pytest.mark.parametrize("modules", ["enabled", "defaults"], ids=["enabled", "default-off"])
def test_legacy_channel_booleans_remain_diagnostic_with_opt_in_modules(modules):
    space = make_space("destination-health-legacy")
    space.enabled_modules = (
        ["telegram", "slack", "discord", "mattermost"]
        if modules == "enabled" else default_enabled_module_keys()
    )
    space.telegram_group_chat_id = "-100-legacy-chat-secret"
    space.set_slack_webhook_url("https://hooks.example/legacy-secret")
    space.save(update_fields=["enabled_modules", "telegram_group_chat_id", "slack_webhook_url"])

    response = get_health(space)

    assert response.data["chat_destinations"]["destinations"] == []
    assert response.data["chat_destinations"]["legacy_channels"] == {
        "telegram": False, "slack": True, "mattermost": False, "discord": False,
    }
    assert response.data["telegram"]["enabled"] is (modules == "enabled")
    assert "legacy-secret" not in json.dumps(response.data)


def test_destination_subsection_exception_returns_safe_unknown_without_optional_fields(monkeypatch):
    space = make_space("destination-health-unavailable")

    def unavailable(_space):
        raise RuntimeError("https://hooks.example/webhook-secret bot-secret chat-secret")

    monkeypatch.setattr(health, "_destinations_section", unavailable)

    response = get_health(space)

    assert response.data["chat_destinations"] == {
        "status": "unknown", "detail": "Chat destination health is unavailable.",
    }
    assert response.data["status"] == "warn"
    assert response.data["worker"]["status"] in {"ok", "warn"}
    assert "secret" not in json.dumps(response.data)


@pytest.mark.parametrize("access", ["foreign", "inventory-manager"])
def test_destination_health_denies_unscoped_or_non_manager_staff(access):
    space = make_space("destination-health-access")
    webhook_destination(space, "slack", "Private room")
    if access == "foreign":
        actor = make_member("foreign-health-manager", make_space("health-actor-home"))
        expected = 404
    else:
        actor = make_member("health-inventory-manager", space, MakerspaceMembership.Role.INVENTORY_MANAGER)
        expected = 403

    response = authenticated_client(actor).get(health_url(space))

    assert response.status_code == expected
    assert "Private room" not in json.dumps(response.data)
