from rest_framework import serializers


class TelegramWebhookSerializer(serializers.Serializer):
    update_id = serializers.IntegerField(required=False)
    callback_query = serializers.DictField(required=False)


class TelegramTestAlertSerializer(serializers.Serializer):
    makerspace_id = serializers.IntegerField()
    message = serializers.CharField(default="Space Works test alert.")


class TelegramTestAlertResultSerializer(serializers.Serializer):
    delivered = serializers.BooleanField()
    reason = serializers.ChoiceField(
        choices=(
            "not_configured", "bad_token", "chat_not_found", "not_in_chat",
            "rate_limited", "unreachable", "token_unreadable", "rejected",
        ),
        required=False,
    )
    detail = serializers.CharField(required=False)
