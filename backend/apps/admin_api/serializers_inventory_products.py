from django.db import transaction
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.inventory import availability, public_image_storage
from apps.inventory.item_codes import CATEGORY_CODE_RE
from apps.inventory.models import (
    Category,
    InventoryProduct,
    PublicAvailabilityMode,
    TrackingMode,
)
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace

QUANTITY_BUCKET_FIELDS = (
    "total_quantity",
    "available_quantity",
    "reserved_quantity",
    "issued_quantity",
    "damaged_quantity",
    "lost_quantity",
)
CREATE_PROTECTED_BUCKET_FIELDS = (
    "reserved_quantity",
    "issued_quantity",
    "damaged_quantity",
    "lost_quantity",
)


class InventoryProductAdminSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        allow_null=True,
        required=False,
    )
    image_url = serializers.SerializerMethodField()
    item_code = serializers.CharField(read_only=True)

    class Meta:
        model = InventoryProduct
        fields = [
            "id",
            "makerspace",
            "box",
            "category",
            "item_code",
            "name",
            "description",
            "image_key",
            "image_url",
            "tracking_mode",
            "total_quantity",
            "available_quantity",
            "reserved_quantity",
            "issued_quantity",
            "damaged_quantity",
            "lost_quantity",
            "needs_fix_quantity",
            "is_public",
            "public_self_checkout_enabled",
            "show_public_count",
            "public_availability_mode",
            "storage_location",
            "is_archived",
            "created_at",
            "updated_at",
        ]
        # makerspace is read-only: it is set from the URL scope on create and must
        # never be reassigned on PATCH, or a manager in one tenant could move a
        # product into another. Box scope is enforced in the view (it knows the
        # authoritative makerspace).
        # needs_fix_quantity is owned by the handover/shelf workflow (never set directly).
        read_only_fields = [
            "id",
            "makerspace",
            "image_key",
            "image_url",
            "needs_fix_quantity",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_image_url(self, obj):
        return public_image_storage.public_url(obj.image_key) or None

    def validate_tracking_mode(self, value):
        if value not in TrackingMode.values:
            raise serializers.ValidationError("Invalid tracking mode.")
        return value

    def validate_public_availability_mode(self, value):
        if value not in PublicAvailabilityMode.values:
            raise serializers.ValidationError("Invalid public availability mode.")
        return value


class InventoryProductAdminCreateSerializer(InventoryProductAdminSerializer):
    class Meta(InventoryProductAdminSerializer.Meta):
        read_only_fields = [
            *InventoryProductAdminSerializer.Meta.read_only_fields,
            *CREATE_PROTECTED_BUCKET_FIELDS,
        ]

    def validate(self, attrs):
        rejected = {
            field: "Use the quantity adjustment workflow after creation."
            for field in CREATE_PROTECTED_BUCKET_FIELDS
            if field in self.initial_data
        }
        if rejected:
            raise serializers.ValidationError(rejected)
        total = attrs.get("total_quantity", 0)
        available = attrs.get("available_quantity", 0)
        if available > total:
            raise serializers.ValidationError(
                {"available_quantity": "Available quantity cannot exceed total quantity."}
            )
        return attrs

    def create(self, validated_data):
        # makerspace is injected by the caller's save(): the admin view passes
        # makerspace_id, the procurement move-to-inventory path passes a makerspace
        # instance. Support both so the shared serializer works for either caller.
        makerspace = validated_data.get("makerspace")
        if makerspace is None:
            makerspace = Makerspace.objects.get(pk=validated_data["makerspace_id"])
        with transaction.atomic():
            limits.check_quota(makerspace, "products", adding=1)
            return super().create(validated_data)


class InventoryProductAdminUpdateSerializer(InventoryProductAdminSerializer):
    class Meta(InventoryProductAdminSerializer.Meta):
        read_only_fields = [
            *InventoryProductAdminSerializer.Meta.read_only_fields,
            *QUANTITY_BUCKET_FIELDS,
        ]

    def validate(self, attrs):
        rejected = {
            field: "Use the quantity adjustment workflow."
            for field in QUANTITY_BUCKET_FIELDS
            if field in self.initial_data
        }
        if rejected:
            raise serializers.ValidationError(rejected)
        return attrs

    def update(self, instance, validated_data):
        # Re-read under the row lock and save only the edited columns: a plain
        # ModelSerializer.update() saves every column from the unlocked instance and
        # would write back stale quantity buckets over a concurrent issue/return.
        tracking_mode = validated_data.pop("tracking_mode", None)
        with transaction.atomic():
            locked = InventoryProduct.objects.select_for_update().get(pk=instance.pk)
            if validated_data.get("is_archived") is False and locked.is_archived:
                limits.check_quota(locked.makerspace, "products", adding=1)
            if tracking_mode is not None:
                locked = availability.change_tracking_mode(locked, tracking_mode)
            for field, value in validated_data.items():
                setattr(locked, field, value)
            if validated_data:
                locked.save(update_fields=[*validated_data, "updated_at"])
            return locked


class CategoryAdminSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False, allow_blank=True)
    code = serializers.CharField(
        required=False, allow_blank=True, max_length=4, trim_whitespace=True
    )
    product_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = [
            "id",
            "makerspace",
            "name",
            "slug",
            "code",
            "display_order",
            "icon",
            "product_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "makerspace",
            "product_count",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        makerspace_id = self.context.get("makerspace_id") or getattr(
            self.instance, "makerspace_id", None
        )
        name = attrs.get("name", getattr(self.instance, "name", None))
        provided_slug = (attrs.get("slug") or "").strip()
        if provided_slug:
            slug = provided_slug
        elif self.instance is not None and self.instance.slug:
            # PATCH that omits slug: keep the existing (possibly custom) slug
            # instead of silently re-deriving it from the name.
            slug = self.instance.slug
        else:
            slug = slugify(name or "")
        if not slug:
            raise serializers.ValidationError(
                {"slug": "Provide a name that yields a valid slug."}
            )
        duplicate = (
            Category.objects.filter(makerspace_id=makerspace_id, slug=slug)
            .exclude(pk=getattr(self.instance, "pk", None))
            .exists()
        )
        if duplicate:
            raise serializers.ValidationError(
                {
                    "slug": "A category with this slug already exists in this makerspace."
                }
            )
        attrs["slug"] = slug
        if "code" in attrs:
            attrs["code"] = self._validated_code(attrs["code"], makerspace_id)
        return attrs

    def _validated_code(self, code, makerspace_id):
        code = code.strip().upper()
        if not code:
            return ""
        if not CATEGORY_CODE_RE.match(code):
            raise serializers.ValidationError({"code": "Use 2–4 capital letters, e.g. MCU."})
        taken = (
            Category.objects.filter(makerspace_id=makerspace_id, code=code)
            .exclude(pk=getattr(self.instance, "pk", None))
            .exists()
        )
        if taken:
            raise serializers.ValidationError(
                {"code": f"Another category in this makerspace already uses {code}."}
            )
        return code
