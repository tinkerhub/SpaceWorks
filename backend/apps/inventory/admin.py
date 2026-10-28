from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.template.response import TemplateResponse
from django.urls import path
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    BooleanRadioFilter,
    ChoicesDropdownFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
    RelatedDropdownFilter,
)

from apps.inventory import availability
from apps.inventory import admin_assets  # noqa: F401
from apps.inventory.admin_bulk_import import bulk_import_view
from apps.inventory.admin_forms import InventoryProductAdminForm
from apps.inventory.admin_quantity_actions import InventoryQuantityActionsMixin
from apps.inventory.admin_image_uploads import PublicImageAdminMixin
from apps.inventory.models import Category, InventoryProduct
from apps.operations import services as operations_services
from apps.operations.serializers import AssetGenerateSerializer
from config.admin_access import SuperuserOnlyModelAdmin
from config.admin_audit import AdminAuditMixin


@admin.register(Category)
class CategoryAdmin(AdminAuditMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("name", "makerspace", "display_order", "slug")
    list_filter = (("makerspace", RelatedDropdownFilter),)
    search_fields = ("name", "slug", "makerspace__name")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("makerspace",)
    ordering = ("display_order", "name")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        # Its products stay in the original space; moving it would cross tenants.
        return fields if obj is None else (*fields, "makerspace")


@admin.register(InventoryProduct)
class InventoryProductAdmin(
    AdminAuditMixin, InventoryQuantityActionsMixin, PublicImageAdminMixin,
    SuperuserOnlyModelAdmin, ModelAdmin,
):
    form = InventoryProductAdminForm
    image_field = "image_key"
    image_kind = "items"
    image_attach_action = "inventory.image_attached"
    image_clear_action = "inventory.image_cleared"
    actions = ["generate_qr_assets", "adjust_quantities", "repair_needs_fix", "scrap_needs_fix"]
    list_display = (
        "name",
        "category",
        "makerspace",
        "box",
        "is_public",
        "public_availability_mode",
        "available_quantity",
        "total_quantity",
        "is_archived",
        "updated_at",
    )
    list_filter = (
        ("makerspace", RelatedDropdownFilter),
        ("category", RelatedDropdownFilter),
        ("box", RelatedDropdownFilter),
        ("public_availability_mode", ChoicesDropdownFilter),
        ("is_public", BooleanRadioFilter),
        ("is_archived", BooleanRadioFilter),
        ("show_public_count", BooleanRadioFilter),
        ("available_quantity", RangeNumericFilter),
        ("total_quantity", RangeNumericFilter),
        ("updated_at", RangeDateTimeFilter),
    )
    search_fields = ("name", "description", "makerspace__name", "makerspace__slug")
    # Admin autocomplete is not yet tenant-scoped; deferred to Phase 2 RBAC.
    # InventoryProduct.clean() is the safety net.
    autocomplete_fields = ("makerspace", "category", "box")
    list_select_related = ("makerspace", "category", "box")
    ordering = ("name",)
    date_hierarchy = "updated_at"
    list_filter_submit = True
    list_per_page = 50
    readonly_fields = ("image_preview",)

    def get_readonly_fields(self, request, obj=None):
        # Tracking mode and buckets change only via the Availability module, from the
        # first save on: stock is added with the "Adjust quantities" action, audited.
        owned = availability.AVAILABILITY_OWNED_FIELDS
        # Its assets and QR codes stay in the original space; moving it would split them.
        tenancy = ("makerspace",) if obj is not None else ()
        return (*super().get_readonly_fields(request, obj), *owned, *tenancy)

    def has_delete_permission(self, request, obj=None):
        # Its assets (and their QR history) cascade from the product; archive it instead.
        return False

    def get_urls(self):
        return [
            path(
                "bulk-import/",
                self.admin_site.admin_view(self.bulk_import_admin_view),
                name="inventory_inventoryproduct_bulk_import",
            ),
        ] + super().get_urls()

    def bulk_import_admin_view(self, request):
        return bulk_import_view(self, request)

    @admin.action(description="Generate QR assets for selected inventory")
    def generate_qr_assets(self, request, queryset):
        if "apply" not in request.POST:
            context = {
                **self.admin_site.each_context(request),
                "title": "Generate QR assets",
                "queryset": queryset,
                "opts": self.model._meta,
                "action_name": "generate_qr_assets",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(request, "admin/inventory/generate_qr_assets.html", context)

        payload = {
            "count": request.POST.get("count"),
            "name_prefix": request.POST.get("name_prefix", ""),
            "create_print_batch": bool(request.POST.get("create_print_batch")),
        }
        print_batch_id = request.POST.get("print_batch_id", "").strip()
        if print_batch_id:
            payload["print_batch_id"] = print_batch_id
        serial_numbers = [
            value.strip()
            for value in request.POST.get("serial_numbers", "").replace(",", "\n").splitlines()
            if value.strip()
        ]
        if serial_numbers:
            payload["serial_numbers"] = serial_numbers

        serializer = AssetGenerateSerializer(data=payload)
        if not serializer.is_valid():
            self.message_user(request, serializer.errors, level=messages.ERROR)
            return None

        success_count = 0
        asset_count = 0
        for product in queryset:
            try:
                created, _batch = operations_services.generate_assets_with_qr(
                    request.user,
                    product,
                    serializer.validated_data,
                )
            except (
                DRFValidationError, DjangoValidationError, DRFPermissionDenied,
                ObjectDoesNotExist, availability.TrackingModeChangeRefused,
            ) as exc:
                self.message_user(request, f"{product.pk}: {exc}", level=messages.ERROR)
            else:
                success_count += 1
                asset_count += len(created)

        if success_count:
            self.message_user(
                request,
                f"Generated {asset_count} QR asset(s) for {success_count} product(s).",
                level=messages.SUCCESS,
            )
        return None
