"""Response serializers specific to the staff machine-type access list."""

from rest_framework import serializers

from apps.machines.service_public_queue import can_manage_public_queue
from apps.machines.metering import MeteringUnit
from apps.machines.models import MachineType
from apps.machines.serializers_machine_types import EffectiveConfigMixin


class MachineTypeAccessSerializer(EffectiveConfigMixin, serializers.ModelSerializer):
    can_create_machine = serializers.BooleanField(read_only=True)
    can_manage_public_queue = serializers.SerializerMethodField()

    def get_can_manage_public_queue(self, obj) -> bool:
        request = self.context.get("request")
        return bool(request and can_manage_public_queue(
            request.user, self.context["makerspace_id"], obj
        ))

    class Meta:
        model = MachineType
        fields = (
            "id",
            "slug",
            "name",
            "icon",
            "is_builtin",
            "managing_action",
            "capability_config",
            "effective_config",
            "makerspace",
            "can_create_machine",
            "can_manage_public_queue",
        )
        read_only_fields = fields


class MachineTypeSettingsSerializer(serializers.Serializer):
    """A built-in type's settings for this makerspace only; null restores the built-in value."""

    metering_unit = serializers.ChoiceField(choices=MeteringUnit.choices, required=False, allow_null=True)
    requires_booking = serializers.BooleanField(required=False, allow_null=True)
    uses_consumables = serializers.BooleanField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Send at least one of metering_unit, requires_booking or uses_consumables.")
        return attrs
