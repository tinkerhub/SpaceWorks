from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.shortcuts import redirect
from rest_framework.exceptions import ValidationError as DRFValidationError
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.operations import services
from apps.operations.admin_forms import StockTransferAdminForm
from apps.operations.models import (
    InventoryAdjustment,
    QrPrintBatch,
    QrPrintBatchItem,
    StockTransfer,
    StockTransferLine,
)
from apps.operations.qr_zip import build_batch_zip
from config.admin_access import SuperuserOnlyModelAdmin
from config.admin_source_gate import admin_tenant_write, gate_refusals

from apps.operations.admin_stocktake import StocktakeLineInline, StocktakeSessionAdmin  # noqa: F401


class StockTransferLineInline(TabularInline):
    # Transfer lines are created by services.apply_stock_transfer with the parent transfer.
    model = StockTransferLine
    extra = 0
    can_delete = False
    readonly_fields = ("transfer", "product", "asset", "quantity", "from_status", "to_status", "notes")
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockTransfer)
class StockTransferAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    # Transfers are created by services.apply_stock_transfer; the admin add view
    # must never fall through to Django's normal ORM save path.
    list_display = ("id", "makerspace", "source_container", "destination_container", "status", "created_at")
    list_filter = ("status", "makerspace")
    readonly_fields = (
        "makerspace",
        "source_container",
        "destination_container",
        "source_makerspace",
        "destination_makerspace",
        "created_by",
        "reason",
        "status",
        "created_at",
        "applied_at",
    )
    fields = readonly_fields
    inlines = (StockTransferLineInline,)

    def get_urls(self):
        return [
            path(
                "add/",
                self.admin_site.admin_view(self.add_transfer_view),
                name="operations_stocktransfer_add",
            ),
        ] + super().get_urls()

    def has_add_permission(self, request):
        return self._has_superuser_access(request)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def add_transfer_view(self, request):
        form = StockTransferAdminForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            makerspace = form.cleaned_data["source_makerspace"]
            destination = form.cleaned_data.get("destination_makerspace")
            try:
                with admin_tenant_write([makerspace.pk, getattr(destination, "pk", None)]):
                    transfer = services.apply_stock_transfer(
                        request.user,
                        makerspace,
                        form.service_payload(),
                    )
            except (DRFValidationError, DjangoValidationError) as exc:
                form.add_error(None, exc)
            except gate_refusals() as exc:
                form.add_error(None, str(exc))
            else:
                self.message_user(
                    request,
                    f"Created stock transfer #{transfer.pk}.",
                    level=messages.SUCCESS,
                )
                return redirect(reverse("admin:operations_stocktransfer_changelist"))

        return TemplateResponse(
            request,
            "admin/operations/stock_transfer_add.html",
            {
                **self.admin_site.each_context(request),
                "title": "Create stock transfer",
                "opts": self.model._meta,
                "form": form,
            },
        )


@admin.register(InventoryAdjustment)
class InventoryAdjustmentAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("id", "makerspace", "product", "asset", "delta_available", "delta_damaged", "delta_lost", "created_at")
    list_filter = ("makerspace",)

    # A ledger row records a quantity change made by `availability.adjust_quantities`; a
    # hand-added row would change no stock, and editing one rewrites history.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # View permission alone renders the read-only page.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class QrPrintBatchItemInline(TabularInline):
    model = QrPrintBatchItem
    extra = 0
    # Items are added by `add_qr_to_batch`, which checks the code is this space's; a raw
    # row could put another tenant's payload in the print ZIP.
    readonly_fields = ("qr_code_display", "label_text", "target_type", "target_id", "sort_order")
    fields = readonly_fields
    can_delete = False

    @admin.display(description="QR code")
    def qr_code_display(self, obj):
        current_qr = obj.qr_code
        if current_qr.makerspace_id != obj.batch.makerspace_id:
            return "QR unavailable"
        opts = current_qr._meta
        url = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=(current_qr.pk,),
            current_app=self.admin_site.name,
        )
        return format_html('<a href="{}">{}</a>', url, str(current_qr))

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(QrPrintBatch)
class QrPrintBatchAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    actions = ["mark_printed_selected", "download_zip_selected"]
    list_display = ("id", "makerspace", "title", "status", "created_at", "printed_at")
    list_filter = ("status", "makerspace")
    inlines = (QrPrintBatchItemInline,)
    # "Printed" is stamped by `mark_batch_printed` via the action, not typed.
    readonly_fields = ("status", "printed_at")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        # Its items are this space's codes; moving the batch would print them for another.
        return fields if obj is None else (*fields, "makerspace")

    @admin.action(description="Mark selected QR print batches as printed")
    def mark_printed_selected(self, request, queryset):
        success_count = 0
        for batch in queryset:
            try:
                services.mark_batch_printed(request.user, batch)
            except (DRFValidationError, DjangoValidationError) as exc:
                self.message_user(request, f"{batch.pk}: {exc}", level=messages.ERROR)
            else:
                success_count += 1

        if success_count:
            self.message_user(request, f"Marked {success_count} QR print batch(es) as printed.", level=messages.SUCCESS)

    @admin.action(description="Download QR ZIP (select exactly one batch)")
    def download_zip_selected(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one batch to download.", level=messages.ERROR)
            return None

        batch = queryset.first()
        try:
            content = build_batch_zip(batch)
        except DRFValidationError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return None

        resp = HttpResponse(content, content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="qr-batch-{batch.pk}.zip"'
        return resp
