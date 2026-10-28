from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.machines.metering import MeteringUnit
from apps.machines.models import MachineType
from apps.machines.type_settings import cached_effective_config


class EffectiveTypeConfigSerializer(serializers.Serializer):
    """A type's settings as they apply in one makerspace (built-in overrides resolved)."""

    metering_unit = serializers.ChoiceField(choices=MeteringUnit.choices)
    requires_booking = serializers.BooleanField()
    uses_consumables = serializers.BooleanField()
    overridden = serializers.BooleanField(help_text="True when this makerspace overrides a built-in setting.")


class EffectiveConfigMixin(serializers.Serializer):
    effective_config = serializers.SerializerMethodField()

    @extend_schema_field(EffectiveTypeConfigSerializer)
    def get_effective_config(self, obj):
        # A custom type belongs to its makerspace; a built-in is resolved for the makerspace
        # the view names (none: the built-in's own settings).
        makerspace_id = obj.makerspace_id or self.context.get("makerspace_id")
        return cached_effective_config(self.context, obj, makerspace_id)


class MachineTypeSerializer(EffectiveConfigMixin, serializers.ModelSerializer):
    class Meta:
        model = MachineType
        fields = [
            'id',
            'slug',
            'name',
            'icon',
            'is_builtin',
            'managing_action',
            'capability_config',
            'effective_config',
            'makerspace',
        ]
        read_only_fields = ['managing_action', 'makerspace', 'capability_config']


class _CustomMachineTypeConfigSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        attrs = super().validate(attrs)
        config = attrs.get("capability_config", getattr(self.instance, "capability_config", None))
        if config is None:
            raise serializers.ValidationError({"capability_config": "Custom machine types require structural configuration."})
        return attrs

    def validate_capability_config(self, value):
        from apps.machines.metering import validate_type_config
        try:
            validate_type_config(value, is_custom=True)
        except Exception as exc:
            raise serializers.ValidationError(getattr(exc, "messages", [str(exc)])) from exc
        return value


class MachineTypeCreateSerializer(_CustomMachineTypeConfigSerializer):
    class Meta:
        model = MachineType
        fields = ['slug', 'name', 'icon', 'capability_config']


class MachineTypeUpdateSerializer(_CustomMachineTypeConfigSerializer):
    class Meta:
        model = MachineType
        fields = ['name', 'icon', 'capability_config']

    def validate_name(self, value):
        duplicate = (
            MachineType.objects.filter(
                makerspace_id=self.instance.makerspace_id,
                name__iexact=value,
            )
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if duplicate:
            raise serializers.ValidationError(
                'A machine type with this name already exists in this makerspace.'
            )
        return value
