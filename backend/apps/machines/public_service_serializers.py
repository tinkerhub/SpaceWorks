"""Public service input and output allowlists; printer fields reuse their validator."""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.machines.printer_capabilities import is_printer_type
from apps.machines.public_printer_service_serializers import (
    PublicPrinterPoolSerializer, PublicPrinterStatusSerializer,
    PublicPrinterSubmitSerializer, PublicPrinterUploadSerializer,
)
from apps.machines.public_service_catalog import eligible_public_pools, public_type_policy


PRINTER_INPUT_FIELDS = frozenset({
    "project_brief", "preferred_settings", "material", "color", "consumable_pool_id",
    "estimated_filament_grams", "quantity",
})


class PublicMachineServiceSubmitSerializer(PublicPrinterSubmitSerializer):
    machine_type_id = serializers.IntegerField(min_value=1, required=False)
    machine_id = serializers.IntegerField(min_value=1, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    capability_payload = serializers.JSONField(required=False)
    queue_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    file_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if ("machine_type_id" in attrs) == ("machine_id" in attrs):
            raise serializers.ValidationError("Supply exactly one of machine_type_id or machine_id.")
        if "machine_type_id" in attrs and "capability_payload" in attrs:
            raise serializers.ValidationError({"capability_payload": "Use the typed printer fields instead."})
        if "machine_id" in attrs and (
            PRINTER_INPUT_FIELDS.intersection(self.initial_data)
            or attrs.get("file_ids") or attrs.get("queue_id") is not None
        ):
            raise serializers.ValidationError("Printer fields and queue attachments require machine_type_id.")
        return attrs


class PublicMachineServiceUploadSerializer(PublicPrinterUploadSerializer):
    machine_type_id = serializers.IntegerField(min_value=1)
    queue_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    kind = serializers.ChoiceField(choices=["stl", "screenshot", "attachment"], required=False)


class PublicServiceUploadSerializer(serializers.Serializer):
    url = serializers.URLField()
    method = serializers.CharField(required=False)
    fields = serializers.DictField(child=serializers.CharField(), required=False)
    headers = serializers.DictField(child=serializers.CharField(), required=False)


class PublicPrinterUploadResponseSerializer(serializers.Serializer):
    file_id = serializers.IntegerField()
    upload = PublicServiceUploadSerializer()


class PublicMachineServiceUploadResponseSerializer(PublicPrinterUploadResponseSerializer):
    queue_id = serializers.IntegerField()


class PublicMachineServiceSubmitResponseSerializer(serializers.Serializer):
    public_token = serializers.UUIDField()
    status = serializers.CharField()


class PublicMachineServiceStatusSerializer(PublicPrinterStatusSerializer):
    """Same PII-free lifecycle allowlist, with the kernel's actual status."""


class PublicServiceFilePolicySerializer(serializers.Serializer):
    allowed_extensions = serializers.ListField(child=serializers.CharField())
    allowed_mimes = serializers.ListField(child=serializers.CharField())
    max_bytes = serializers.IntegerField()


class PublicMachineServiceTypeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    icon = serializers.CharField()
    is_printer = serializers.SerializerMethodField()
    file_policy = serializers.SerializerMethodField()
    materials = serializers.SerializerMethodField()
    colors = serializers.SerializerMethodField()
    consumable_pools = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField())
    def get_is_printer(self, obj):
        return is_printer_type(obj)

    @extend_schema_field(PublicServiceFilePolicySerializer)
    def get_file_policy(self, obj):
        policy = public_type_policy(obj)
        return PublicServiceFilePolicySerializer(policy).data

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_materials(self, obj):
        return obj.capability_config.get("accepted_materials", []) if is_printer_type(obj) else []

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_colors(self, obj):
        return obj.capability_config.get("accepted_colours", []) if is_printer_type(obj) else []

    @extend_schema_field(PublicPrinterPoolSerializer(many=True))
    def get_consumable_pools(self, obj):
        if not is_printer_type(obj):
            return []
        pools = eligible_public_pools(self.context["makerspace"], obj)
        return PublicPrinterPoolSerializer(pools, many=True).data
