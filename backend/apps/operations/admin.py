from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.shortcuts import redirect
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from django.template.response import TemplateResponse
from django.urls import path, reverse
from unfold.admin import ModelAdmin, TabularInline

from apps.makerspaces.guards import require_module
from apps.operations import services
from apps.operations.admin_forms import StockTransferAdminForm, StocktakeCountAdminForm
from apps.operations.models import (
    InventoryAdjustment,
    QrPrintBatch,
    QrPrintBatchItem,
    StockTransfer,
    StockTransferLine,
    StocktakeLine,
    StocktakeSession,
)
from apps.operations.qr_zip import build_batch_zip
from config.admin_access import SuperuserOnlyModelAdmin


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
            try:
                transfer = services.apply_stock_transfer(
                    request.user,
                    makerspace,
                    form.service_payload(),
                )
            except (DRFValidationError, DjangoValidationError) as exc:
                form.add_error(None, exc)
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


class StocktakeLineInline(TabularInline):
    model = StocktakeLine
    extra = 0
    can_delete = False
    readonly_fields = (
        "stocktake",
        "product",
        "asset",
        "container",
        "expected_quantity",
        "counted_quantity",
        "variance_quantity",
        "condition",
        "notes",
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StocktakeSession)
class StocktakeSessionAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    actions = ["complete_selected", "approve_selected", "apply_adjustments_selected"]
    list_display = ("id", "makerspace", "container", "status", "started_at", "approved_at")
    list_filter = ("status", "makerspace")
    inlines = (StocktakeLineInline,)
    # Completing, approving (by a different person) and applying adjust stock; only the
    # actions run that workflow, so the lifecycle fields are not hand-editable.
    def get_readonly_fields(self, request, obj=None):
        return (
            *super().get_readonly_fields(request, obj), "makerspace", "container", "status",
            "started_by", "completed_by", "completed_at", "approved_by", "approved_at",
        )

    def has_add_permission(self, request):
        # `create_stocktake` checks the module and the container's tenancy and audits;
        # a hand-made session would do none of that. Start one from the console.
        return False

    def has_delete_permission(self, request, obj=None):
        # Ledger entries cascade from the session, so a delete would rewrite stock history.
        return False

    def get_urls(self):
        return [
            path(
                "<path:object_id>/count/",
                self.admin_site.admin_view(self.count_line_view),
                name="operations_stocktakesession_count",
            ),
        ] + super().get_urls()

    @admin.action(description="Complete selected stocktakes")
    def complete_selected(self, request, queryset):
        self._run_stocktake_action(request, queryset, services.complete_stocktake, "Completed")

    @admin.action(description="Approve selected stocktakes")
    def approve_selected(self, request, queryset):
        self._run_stocktake_action(request, queryset, services.approve_stocktake, "Approved")

    @admin.action(description="Apply selected stocktake adjustments")
    def apply_adjustments_selected(self, request, queryset):
        self._run_stocktake_action(request, queryset, services.apply_stocktake_adjustments, "Applied adjustments for")

    def _run_stocktake_action(self, request, queryset, service_func, success_label):
        success_count = 0
        for stocktake in queryset:
            try:
                service_func(request.user, stocktake)
            except (DRFValidationError, DjangoValidationError, DRFPermissionDenied) as exc:
                self.message_user(request, f"{stocktake.pk}: {exc}", level=messages.ERROR)
            else:
                success_count += 1

        if success_count:
            self.message_user(request, f"{success_label} {success_count} stocktake(s).", level=messages.SUCCESS)

    def count_line_view(self, request, object_id):
        stocktake = self.get_queryset(request).filter(pk=object_id).first()
        if stocktake is None:
            self.message_user(request, "Stocktake was not found.", level=messages.ERROR)
            return redirect(reverse("admin:operations_stocktakesession_changelist"))
        try:
            require_module(stocktake.makerspace, "stocktake")
        except DRFValidationError as exc:
            self.message_user(request, exc.detail, level=messages.ERROR)
            return redirect(reverse("admin:operations_stocktakesession_change", args=[stocktake.pk]))
        if stocktake.status not in {StocktakeSession.Status.DRAFT, StocktakeSession.Status.COUNTING}:
            self.message_user(
                request,
                "Count lines can only be added while a stocktake is draft or counting.",
                level=messages.ERROR,
            )
            return redirect(reverse("admin:operations_stocktakesession_change", args=[stocktake.pk]))

        form = StocktakeCountAdminForm(request.POST or None, stocktake=stocktake)
        if request.method == "POST" and form.is_valid():
            try:
                line = services.add_stocktake_line(
                    request.user,
                    stocktake,
                    form.cleaned_data["_validated_payload"],
                )
            except (DRFValidationError, DjangoValidationError) as exc:
                form.add_error(None, exc)
            else:
                self.message_user(
                    request,
                    f"Counted stocktake line #{line.pk}.",
                    level=messages.SUCCESS,
                )
                return redirect(reverse("admin:operations_stocktakesession_change", args=[stocktake.pk]))

        return TemplateResponse(
            request,
            "admin/operations/stocktake_count.html",
            {
                **self.admin_site.each_context(request),
                "title": "Count stocktake line",
                "opts": self.model._meta,
                "stocktake": stocktake,
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
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False


class QrPrintBatchItemInline(TabularInline):
    model = QrPrintBatchItem
    extra = 0
    # Items are added by `add_qr_to_batch`, which checks the code is this space's; a raw
    # row could put another tenant's payload in the print ZIP.
    readonly_fields = ("qr_code", "label_text", "target_type", "target_id", "sort_order")
    can_delete = False

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
        resp = HttpResponse(build_batch_zip(batch), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="qr-batch-{batch.pk}.zip"'
        return resp
