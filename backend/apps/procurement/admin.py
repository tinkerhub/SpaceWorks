from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.procurement.models import ToBuyItem, ToBuyReceipt
from apps.procurement.services import stamp_status_change
from apps.separability.tombstones import app_is_tombstoned
from config.admin_access import SuperuserOnlyModelAdmin


class ToBuyItemAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "name",
        "makerspace",
        "kind",
        "machine_type",
        "quantity",
        "status",
        "vendor_name",
        "purchaser",
        "created_by",
        "created_at",
    )
    list_filter = ("kind", "status", "machine_type", "makerspace")
    search_fields = ("name", "link", "vendor_name", "makerspace__name", "makerspace__slug")
    readonly_fields = ("created_by", "purchaser", "ordered_at", "received_at", "created_at", "updated_at")
    fields = (
        "makerspace",
        "kind",
        "machine_type",
        "name",
        "quantity",
        "link",
        "status",
        "estimated_unit_cost",
        "vendor_name",
        "actual_unit_cost",
        "purchaser",
        "ordered_at",
        "received_at",
        "created_by",
        "created_at",
        "updated_at",
    )

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        # The API fixes both at creation; a moved or re-kinded item would carry the old
        # space's machine type and audit trail.
        return fields if obj is None else (*fields, "makerspace", "kind")

    def save_model(self, request, obj, form, change):
        previous = ToBuyItem.objects.filter(pk=obj.pk).values_list("status", flat=True).first() if change else None
        super().save_model(request, obj, form, change)
        stamp_status_change(obj, request.user, previous)


class ToBuyReceiptAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("id", "to_buy_item", "uploaded_by", "created_at")
    search_fields = ("object_key", "to_buy_item__name", "to_buy_item__makerspace__name")
    readonly_fields = ("to_buy_item", "object_key", "uploaded_by", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# Registered rather than decorated, because the admin surface is exactly what a
# tombstone removes: the rows are retained and still reachable through the ORM and
# the purge path, but the deployment does not offer a screen for a module it no
# longer ships. The classes stay defined either way so the module still imports.
if not app_is_tombstoned("procurement"):
    admin.site.register(ToBuyItem, ToBuyItemAdmin)
    admin.site.register(ToBuyReceipt, ToBuyReceiptAdmin)
