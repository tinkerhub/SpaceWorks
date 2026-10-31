"""Protected readonly local authority with one explicit POST retry route."""

import uuid

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from unfold.admin import ModelAdmin

from config.admin_access import SuperuserOnlyModelAdmin
from .models import Makerspace, ModulePurgeReceipt
from .module_purge_receipts import retry_cleanup
from .purge_intent import require_actor


def origin_allows(request, maker_id):
    from .origin_scope import AMBIGUOUS_STAFF_ORIGIN_SCOPE, NO_STAFF_ORIGIN_SCOPE, staff_origin_scope

    scope = staff_origin_scope(request)
    return scope is NO_STAFF_ORIGIN_SCOPE or (scope is not AMBIGUOUS_STAFF_ORIGIN_SCOPE and scope == maker_id)


@require_POST
def retry_cleanup_view(request, receipt_id, model_admin):
    try:
        require_actor(request.user)
    except ValidationError:
        return HttpResponseForbidden("An active unrestricted superuser is required.")
    if (request.GET or set(request.POST) - {"csrfmiddlewaretoken"}
            or any(len(values) != 1 for _, values in request.POST.lists())):
        return HttpResponseBadRequest("Unexpected or mixed cleanup parameters.")
    try:
        raw = str(receipt_id)
        if len(raw) != 36:
            raise ValueError
        parsed = uuid.UUID(raw)
        if str(parsed) != raw:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return HttpResponseBadRequest("A canonical receipt UUID is required.")
    receipt = model_admin.get_queryset(request).filter(pk=parsed).first()
    if receipt is None:
        raise Http404
    if not origin_allows(request, receipt.source_makerspace_id):
        return HttpResponseForbidden("The current staff origin cannot access this makerspace.")
    try:
        receipt = retry_cleanup(parsed, request.user)
    except Exception:
        # Exceptions can contain provider URLs/locators: show only a safe outcome.
        model_admin.message_user(request, "Cleanup is unconfirmed; the receipt and original charges remain retained.", level=messages.ERROR)
    else:
        model_admin.message_user(request, f"Graph removed; storage last verified {receipt.last_verified_at.isoformat()}. Late-upload cleanup remains available.", level=messages.SUCCESS)
    return HttpResponseRedirect(reverse("admin:makerspaces_modulepurgereceipt_change", args=[parsed]))


@admin.register(ModulePurgeReceipt)
class ModulePurgeReceiptAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("id", "source_makerspace_id", "module_key", "intent_created_at", "graph_purged_at", "last_verified_at", "invalidated_at", "last_error_code")
    readonly_fields = tuple(field.name for field in ModulePurgeReceipt._meta.concrete_fields)
    actions = None
    change_form_template = "admin/makerspaces/module_purge_receipt.html"

    def get_queryset(self, request):
        rows = super().get_queryset(request)
        if not self._has_superuser_access(request):
            return rows.none()
        spaces = Makerspace._base_manager.filter(
            pk=OuterRef("source_makerspace_id"), public_code=OuterRef("source_public_code"),
            created_at=OuterRef("source_created_at"), superadmin_access_enabled=True,
        )
        rows = rows.annotate(_visible_maker=Exists(spaces)).filter(_visible_maker=True)
        from .origin_scope import AMBIGUOUS_STAFF_ORIGIN_SCOPE, NO_STAFF_ORIGIN_SCOPE, staff_origin_scope

        scope = staff_origin_scope(request)
        if scope is AMBIGUOUS_STAFF_ORIGIN_SCOPE:
            return rows.none()
        return rows if scope is NO_STAFF_ORIGIN_SCOPE else rows.filter(source_makerspace_id=scope)

    def has_view_permission(self, request, obj=None):
        return (super().has_view_permission(request, obj)
                and (obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        from .urls_admin_module_purge_receipts import receipt_urls

        return receipt_urls(self) + super().get_urls()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = dict(extra_context or {})
        extra_context["cleanup_url"] = reverse("admin:makerspaces_modulepurgereceipt_retry_cleanup", args=[object_id])
        return super().change_view(request, object_id, form_url, extra_context)
