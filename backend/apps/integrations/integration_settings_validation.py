"""Boundary validation for the per-makerspace Telegram fields and stored secrets.

Shared by both write paths that accept them (`/admin/makerspace/<id>/api-settings` and
the makerspace PATCH), so a value one accepts the other cannot refuse.
"""

import re

from django.conf import settings
from rest_framework import serializers
from rest_framework.exceptions import APIException

# BotFather tokens are `<bot id>:<secret>`. The token is placed in the Bot API URL path,
# so anything outside this alphabet (a slash, `?`, whitespace from a sloppy paste) is
# refused here rather than sent to Telegram as part of a different URL.
_BOT_TOKEN = re.compile(r"^\d{3,20}:[A-Za-z0-9_-]{20,80}$")
# A numeric chat ID (groups are negative, supergroups start with -100) or a public
# `@channelname`.
_CHAT_ID = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{3,31})$")

SECRET_FIELDS = (
    "telegram_bot_token",
    "smtp_password",
    "slack_webhook_url",
    "mattermost_webhook_url",
    "discord_webhook_url",
)


class SecretStorageUnavailable(APIException):
    status_code = 503
    default_code = "secret_storage_unavailable"
    default_detail = (
        "Secrets can't be saved on this server because its encryption key "
        "(API_CLIENT_ENC_KEY) isn't set. Ask the platform administrator to set it."
    )


def validate_telegram_bot_token(value):
    value = (value or "").strip()
    if value and not _BOT_TOKEN.match(value):
        raise serializers.ValidationError(
            "That isn't a Telegram bot token. Copy the whole token BotFather gave you; it "
            "looks like 123456789:AAE…"
        )
    return value


def validate_telegram_chat_id(value):
    value = (value or "").strip()
    if value and not _CHAT_ID.match(value):
        raise serializers.ValidationError(
            "Enter the group's numeric chat ID (for example -1001234567890) or a public "
            "@channel name."
        )
    return value


def require_secret_storage(attrs):
    """Refuse, readably, to store a non-empty secret the server cannot encrypt.

    Without this the encrypt call raises `ImproperlyConfigured` deep inside `save()` and
    the operator sees a bare 500. Clearing a secret (empty string) stores nothing
    encrypted, so it stays allowed.
    """
    if settings.API_CLIENT_ENC_KEY:
        return
    if any(attrs.get(field) for field in SECRET_FIELDS):
        raise SecretStorageUnavailable()
