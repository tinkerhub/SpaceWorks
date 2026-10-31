"""The sole confirmed HTTP entry into synchronous makerspace purge."""

import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from apps.backup.not_restored import TenantNotRestored
from apps.backup.operation_lock import OperationLockUnavailable
from apps.makerspaces.lifecycle_purge import purge
from apps.makerspaces.models import Makerspace
from apps.makerspaces.purge_intent import PurgePending, require_actor
from apps.tenant_migration.gate_errors import SourceMigrationGateError


logger = logging.getLogger(__name__)


def confirmation_page(model_admin, request, makerspaces, *, outcomes=()):
    return TemplateResponse(request, "admin/makerspaces/purge_confirmation.html", {
        **model_admin.admin_site.each_context(request),
        "title": "Purge selected archived makerspaces",
        "queryset": makerspaces, "opts": model_admin.model._meta,
        "confirm_url": reverse("admin:makerspaces_makerspace_purge_confirmed"),
        "changelist_url": reverse("admin:makerspaces_makerspace_changelist"),
        "outcomes": outcomes,
    })


@require_POST
def confirmed_purge_view(request, model_admin):
    try:
        require_actor(request.user)
    except ValidationError as exc:
        return HttpResponseForbidden(str(exc))
    ids = request.POST.getlist("makerspace_id")
    if (not ids or len(ids) > 100 or len(set(ids)) != len(ids)
            or any(not _valid_id(value) for value in ids)):
        return HttpResponseBadRequest("Invalid makerspace selection.")
    allowed = {"csrfmiddlewaretoken", "makerspace_id"} | {f"slug_{value}" for value in ids}
    if set(request.POST) - allowed or any(
        len(request.POST.getlist(key)) != 1 for key in set(request.POST) - {"makerspace_id"}
    ):
        return HttpResponseBadRequest("Unexpected or mixed purge action parameters.")
    spaces = list(Makerspace.objects.filter(pk__in=ids).order_by("pk"))
    if len(spaces) != len(ids) or any(
        request.POST.get(f"slug_{space.pk}") != space.slug for space in spaces
    ):
        return HttpResponseBadRequest("Selection or exact slug confirmation did not match.")
    remaining, outcomes = [], []
    for space in spaces:
        label = f"{space.name} ({space.slug})"
        try:
            receipt = purge(space, request.user)
        except PurgePending as exc:
            remaining.append(space)
            outcomes.append(f"{label}: {exc.messages[0]}")
        except (ValidationError, OperationLockUnavailable, SourceMigrationGateError, TenantNotRestored) as exc:
            remaining.append(space)
            outcomes.append(f"{label}: {exc}")
        except Exception:
            # Never turn a provider/transaction failure into a success message.
            logger.exception("makerspace_purge_refused", extra={"makerspace_id": space.pk})
            remaining.append(space)
            outcomes.append(f"{label}: Purge completion is unconfirmed; refresh before retrying.")
        else:
            outcome = format_html(
                '{}: Tenant graph removed. Storage verified at {}. Late-upload cleanup remains available. <a href="{}">View receipt</a>.',
                label, receipt.last_verified_at.isoformat(),
                reverse("admin:makerspaces_purgereceipt_change", args=[receipt.pk]),
            )
            model_admin.message_user(request, outcome, level=messages.SUCCESS)
            outcomes.append(outcome)
    return confirmation_page(model_admin, request, remaining, outcomes=outcomes)


def _valid_id(value):
    # Bound strings before int(): Python's digit limit and PostgreSQL bigint range
    # must never turn authenticated malformed input into a 500.
    return (isinstance(value, str) and 0 < len(value) <= 10 and value.isascii()
            and value.isdecimal() and value[0] != "0"
            and int(value) <= 2147483647)
