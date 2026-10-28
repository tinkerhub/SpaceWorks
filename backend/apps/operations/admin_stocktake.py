"""Stocktake sessions in /control/: lifecycle via actions, counts via a gated custom view."""

from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from unfold.admin import ModelAdmin, TabularInline

from apps.makerspaces.guards import require_module
from apps.operations import services
from apps.operations.admin_forms import StocktakeCountAdminForm
from apps.operations.models import StocktakeLine, StocktakeSession
from config.admin_access import SuperuserOnlyModelAdmin
from config.admin_source_gate import admin_tenant_write, gate_refusals


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
                with admin_tenant_write([stocktake.makerspace_id]):
                    line = services.add_stocktake_line(
                        request.user,
                        stocktake,
                        form.cleaned_data["_validated_payload"],
                    )
            except (DRFValidationError, DjangoValidationError) as exc:
                form.add_error(None, exc)
            except gate_refusals() as exc:
                form.add_error(None, str(exc))
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
