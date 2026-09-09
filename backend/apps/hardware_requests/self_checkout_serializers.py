from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


class _CheckinPrincipalSerializer(serializers.Serializer):
    checkin_mid = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def to_internal_value(self, data):
        if not self.context.get("checkin_submission", False):
            # These inputs have no meaning outside the checked-in policy. Drop them
            # before field validation so adding the seam cannot change legacy
            # responses for callers that happened to include similarly named keys.
            data = data.copy()
            data.pop("checkin_mid", None)
            data.pop("name", None)
        return super().to_internal_value(data)

    def validate(self, attrs):
        if self.context.get("checkin_submission", False) and not attrs.get(
            "name", ""
        ).strip():
            raise serializers.ValidationError({"name": "This field is required."})
        return attrs


class PublicToolScanSerializer(_CheckinPrincipalSerializer):
    payload = serializers.CharField(max_length=64)
    evidence_id = serializers.IntegerField()
    remark = serializers.CharField()
    report_problem = serializers.BooleanField(required=False, default=False)
    problem_note = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("report_problem") and not attrs.get("problem_note", "").strip():
            raise serializers.ValidationError(
                {"problem_note": "Problem note is required."}
            )
        return attrs


class PublicToolCheckoutSerializer(_CheckinPrincipalSerializer):
    payload = serializers.CharField(max_length=64, required=False)
    qr_payloads = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
        max_length=50,
    )
    evidence_id = serializers.IntegerField()
    remark = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        has_payload = "payload" in attrs
        has_batch = bool(attrs.get("qr_payloads"))
        if not has_payload and not has_batch:
            raise serializers.ValidationError(
                {"payload": "This field is required unless qr_payloads is provided."}
            )
        if has_payload and has_batch:
            raise serializers.ValidationError(
                "Provide either payload or qr_payloads, not both."
            )
        return attrs


class PublicToolEvidenceUrlRequestSerializer(_CheckinPrincipalSerializer):
    evidence_type = serializers.ChoiceField(choices=["issue", "return"])
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class PublicToolLoanItemSerializer(serializers.Serializer):
    product_name = serializers.CharField()
    quantity = serializers.IntegerField()


class PublicToolLoanSerializer(serializers.Serializer):
    public_token = serializers.UUIDField(source="request.public_token", read_only=True)
    status = serializers.CharField(read_only=True)
    items = serializers.SerializerMethodField()

    @extend_schema_field(PublicToolLoanItemSerializer(many=True))
    def get_items(self, obj) -> list[dict[str, object]]:
        if "items" in getattr(obj.request, "_prefetched_objects_cache", {}):
            items = sorted(obj.request.items.all(), key=lambda item: item.product.name)
        else:
            items = obj.request.items.select_related("product").order_by("product__name")
        return [
            {"product_name": item.product.name, "quantity": item.issued_quantity}
            for item in items
        ]
