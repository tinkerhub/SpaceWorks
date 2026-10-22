from rest_framework import serializers

from apps.operations.models import StocktakeLine, StocktakeSession
from apps.operations.stocktake_authority import can_review_stocktake


class StocktakeCreateSerializer(serializers.Serializer):
    container_id = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class StocktakeLineInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(required=False)
    asset_id = serializers.IntegerField(required=False)
    container_id = serializers.IntegerField(required=False, allow_null=True)
    counted_quantity = serializers.IntegerField(min_value=0)
    condition = serializers.ChoiceField(choices=StocktakeLine.Condition.choices, default=StocktakeLine.Condition.AVAILABLE)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if bool(attrs.get("product_id")) == bool(attrs.get("asset_id")):
            raise serializers.ValidationError("Provide exactly one of product_id or asset_id.")
        return attrs


class StocktakeScanInputSerializer(serializers.Serializer):
    payload = serializers.CharField(max_length=64)


class StocktakeScanResultSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["box", "asset", "product"])
    container_id = serializers.IntegerField(required=False)
    asset_id = serializers.IntegerField(required=False)
    product_id = serializers.IntegerField(required=False)
    label = serializers.CharField(required=False)
    code = serializers.CharField(required=False)
    asset_tag = serializers.CharField(required=False)
    product = serializers.CharField(required=False)
    name = serializers.CharField(required=False)
    status = serializers.CharField(required=False)


class StocktakeLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = StocktakeLine
        fields = [
            "id",
            "product",
            "asset",
            "container",
            "expected_quantity",
            "counted_quantity",
            "variance_quantity",
            "condition",
            "notes",
        ]


class StocktakeSerializer(serializers.ModelSerializer):
    lines = StocktakeLineSerializer(many=True, read_only=True)
    # Server-derived for the requesting user, so the console shows Approve/Apply only to
    # someone the locked service will actually accept (never inferred client-side).
    can_approve = serializers.SerializerMethodField()
    can_apply = serializers.SerializerMethodField()

    class Meta:
        model = StocktakeSession
        fields = [
            "id",
            "makerspace",
            "container",
            "status",
            "started_by",
            "completed_by",
            "approved_by",
            "started_at",
            "completed_at",
            "approved_at",
            "notes",
            "lines",
            "can_approve",
            "can_apply",
        ]

    def get_can_approve(self, obj) -> bool:
        return obj.status == StocktakeSession.Status.COMPLETED and self._can_review(obj)

    def get_can_apply(self, obj) -> bool:
        return obj.status == StocktakeSession.Status.APPROVED and self._can_review(obj)

    def _can_review(self, obj):
        request = self.context.get("request")
        return bool(request) and can_review_stocktake(request.user, obj)
