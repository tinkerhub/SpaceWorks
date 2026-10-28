"""Quantity actions on InventoryProduct in /control/: every bucket move goes through the
Availability module (the only place quantity counts change) and is audited."""

from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import transaction
from django.template.response import TemplateResponse

from apps.audit import services as audit
from apps.inventory import availability
from apps.inventory.admin_forms import InventoryQuantityAdjustmentForm, NeedsFixQuantityForm


class InventoryQuantityActionsMixin:
    @admin.action(description="Adjust selected inventory quantities")
    def adjust_quantities(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Select exactly one inventory product to adjust quantities.",
                level=messages.ERROR,
            )
            return None

        product = queryset.first()
        if "apply" not in request.POST:
            context = {
                **self.admin_site.each_context(request),
                "title": "Adjust inventory quantities",
                "queryset": queryset,
                "opts": self.model._meta,
                "action_name": "adjust_quantities",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
                "product": product,
            }
            return TemplateResponse(
                request,
                "admin/inventory/adjust_quantities.html",
                context,
            )

        form = InventoryQuantityAdjustmentForm(request.POST)
        if not form.is_valid():
            self.message_user(request, form.errors, level=messages.ERROR)
            return None

        data = form.cleaned_data
        try:
            locked = availability.adjust_quantities(
                product,
                delta_available=data["delta_available"],
                delta_damaged=data["delta_damaged"],
                delta_lost=data["delta_lost"],
                reason=data["reason"],
                actor=request.user,
            )
        except availability.InsufficientStock as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
        else:
            self.message_user(
                request,
                (
                    f"Updated quantities for {locked}: available="
                    f"{locked.available_quantity}, damaged={locked.damaged_quantity}, "
                    f"lost={locked.lost_quantity}."
                ),
                level=messages.SUCCESS,
            )
        return None

    @admin.action(description="Repair units from the needs-fix shelf")
    def repair_needs_fix(self, request, queryset):
        return self._needs_fix_action(
            request,
            queryset,
            action_name="repair_needs_fix",
            action_label="repair",
            service=availability.repair_from_needs_fix,
        )

    @admin.action(description="Scrap units from the needs-fix shelf")
    def scrap_needs_fix(self, request, queryset):
        return self._needs_fix_action(
            request,
            queryset,
            action_name="scrap_needs_fix",
            action_label="scrap",
            service=availability.scrap_from_needs_fix,
        )

    def _needs_fix_action(self, request, queryset, *, action_name, action_label, service):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Select exactly one inventory product.",
                level=messages.ERROR,
            )
            return None

        product = queryset.first()
        if "apply" not in request.POST:
            context = {
                **self.admin_site.each_context(request),
                "title": f"{action_label.title()} needs-fix units",
                "queryset": queryset,
                "opts": self.model._meta,
                "action_name": action_name,
                "action_label": action_label,
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
                "product": product,
            }
            return TemplateResponse(
                request,
                "admin/inventory/needs_fix_quantity.html",
                context,
            )

        form = NeedsFixQuantityForm(request.POST)
        if not form.is_valid():
            self.message_user(request, form.errors, level=messages.ERROR)
            return None

        quantity = form.cleaned_data["quantity"]
        try:
            with transaction.atomic():
                locked = service(product, quantity)
                audit.record(
                    request.user,
                    f"inventory.needs_fix_{action_label}",
                    makerspace=locked.makerspace,
                    target=locked,
                    meta={"quantity": quantity},
                )
        except availability.InsufficientStock as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"{action_label.title()}ed {quantity} unit(s) for {locked}.",
                level=messages.SUCCESS,
            )
        return None
