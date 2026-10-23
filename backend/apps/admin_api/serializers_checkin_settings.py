"""Shapes for a makerspace's Check-in settings card."""

from rest_framework import serializers

from apps.checkin.transport import tenant_url_error
from apps.makerspaces.request_access import MODE_CHOICES


def _validate_roster_url(value):
    """Blank clears (deployment default applies); otherwise the outbound SSRF guard."""
    raw = (value or "").strip()
    if raw:
        error = tenant_url_error(raw)
        if error:
            raise serializers.ValidationError(error)
    return raw


class CheckinDeploymentDefaultsSerializer(serializers.Serializer):
    api_url = serializers.CharField(allow_blank=True)
    required_purpose = serializers.CharField(allow_blank=True)
    provider_name = serializers.CharField(allow_blank=True)


class CheckinEffectiveSerializer(serializers.Serializer):
    api_url_source = serializers.ChoiceField(
        choices=[("makerspace", "makerspace"), ("deployment", "deployment"), ("", "none")],
        allow_blank=True,
    )
    required_purpose = serializers.CharField(allow_blank=True)
    provider_name = serializers.CharField(allow_blank=True)


class CheckinSettingsSerializer(serializers.Serializer):
    public_request_mode = serializers.ChoiceField(choices=MODE_CHOICES)
    request_access = serializers.CharField()
    membership_installed = serializers.BooleanField()
    checkin_space_id = serializers.IntegerField(allow_null=True)
    checkin_api_url = serializers.CharField(allow_blank=True)
    checkin_required_purpose = serializers.CharField(allow_blank=True)
    checkin_provider_name = serializers.CharField(allow_blank=True)
    deployment = CheckinDeploymentDefaultsSerializer()
    effective = CheckinEffectiveSerializer()


class CheckinSettingsUpdateSerializer(serializers.Serializer):
    public_request_mode = serializers.ChoiceField(choices=MODE_CHOICES, required=False)
    checkin_space_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    checkin_api_url = serializers.CharField(
        max_length=500, allow_blank=True, required=False, trim_whitespace=True
    )
    checkin_required_purpose = serializers.CharField(
        max_length=200, allow_blank=True, required=False, trim_whitespace=True
    )
    checkin_provider_name = serializers.CharField(
        max_length=100, allow_blank=True, required=False, trim_whitespace=True
    )

    def validate_checkin_api_url(self, value):
        return _validate_roster_url(value)


class CheckinTestRequestSerializer(serializers.Serializer):
    checkin_api_url = serializers.CharField(
        max_length=500, allow_blank=True, required=False, trim_whitespace=True,
        help_text="Candidate URL to test. Blank tests the saved (or deployment) roster.",
    )


class CheckinTestResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    rows = serializers.IntegerField(help_text="Valid roster rows read.")
    space_rows = serializers.IntegerField(
        allow_null=True,
        help_text="Rows for this makerspace's space ID; null when none is bound.",
    )
    code = serializers.CharField(allow_blank=True)
    reason = serializers.CharField(allow_blank=True)


class CheckinSettingsErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
