from rest_framework import serializers


class CheckinLookupRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)


class CheckinMatchSerializer(serializers.Serializer):
    """One roster entry that matched the typed name.

    `mid` is returned so the client can send back WHICH match it confirmed, and the
    server re-verifies it against a fresh roster on submit -- this response is never
    a token. `avatar` is what makes two people sharing a display name
    distinguishable, which is the whole reason the confirm step exists.
    """

    mid = serializers.IntegerField()
    name = serializers.CharField()
    avatar = serializers.CharField(allow_blank=True)
    purpose = serializers.CharField(allow_blank=True)
    project_name = serializers.CharField(allow_blank=True)
    eligible = serializers.BooleanField()
    reason = serializers.ChoiceField(
        choices=[("", "eligible"), ("purpose", "purpose"), ("project", "project"),
                 ("expired", "expired"), ("space", "space")],
        allow_blank=True,
    )
