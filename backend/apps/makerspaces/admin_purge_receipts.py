"""Readonly receipt provenance with one explicit, CSRF-protected cleanup action."""

import logging
import uuid

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from unfold.admin import ModelAdmin

from config.admin_access import SuperuserOnlyModelAdmin
from .models import PurgeReceipt
from .purge_intent import require_actor
from .purge_receipts import retry_cleanup

logger = logging.getLogger(__name__)


@require_POST
def retry_cleanup_view(request, receipt_id, model_admin):
    try:
        require_actor(request.user)
    except ValidationError as exc:
        return HttpResponseForbidden(str(exc))
    if set(request.POST) - {"csrfmiddlewaretoken"} or any(len(values) != 1 for _, values in request.POST.lists()):
        return HttpResponseBadRequest("Unexpected cleanup parameters.")
    try:
        parsed = uuid.UUID(str(receipt_id))
        if str(parsed) != str(receipt_id):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return HttpResponseBadRequest("Invalid receipt ID.")
    try:
        receipt = retry_cleanup(parsed, request.user)
    except PurgeReceipt.DoesNotExist as exc:
        raise Http404 from exc
    except Exception:
        logger.exception("purge_receipt_cleanup_unconfirmed", extra={"receipt_id": str(parsed)})
        model_admin.message_user(request, "Cleanup completion is unconfirmed. Refresh this receipt before retrying.", level=messages.ERROR)
    else:
        model_admin.message_user(request, f"Storage verified at {receipt.last_verified_at.isoformat()}. Late-upload cleanup remains available.", level=messages.SUCCESS)
    return HttpResponseRedirect(reverse("admin:makerspaces_purgereceipt_change", args=[parsed]))


@admin.register(PurgeReceipt)
class PurgeReceiptAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("id", "source_makerspace_id", "graph_purged_at", "last_verified_at", "invalidated_at", "last_error_code")
    readonly_fields = tuple(field.name for field in PurgeReceipt._meta.concrete_fields)
    actions = None
    change_form_template = "admin/makerspaces/purge_receipt.html"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        from .urls_admin_purge_receipts import receipt_urls

        return receipt_urls(self) + super().get_urls()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = dict(extra_context or {})
        extra_context["cleanup_url"] = reverse("admin:makerspaces_purgereceipt_retry_cleanup", args=[object_id])
        return super().change_view(request, object_id, form_url, extra_context)
