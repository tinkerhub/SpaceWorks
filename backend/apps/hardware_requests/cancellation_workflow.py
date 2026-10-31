"""Staff cancellation of an accepted request before any physical handover."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.encryption.write_fence import assert_mapped_write_allowed
from apps.hardware_requests import notifications
from apps.hardware_requests.handover_workflow import clear_unissued_assignment
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItemAsset,
    PublicToolLoan,
    RequesterAccountability,
    ReturnEvent,
)
from apps.hardware_requests.workflow_errors import InvalidTransition, RequestValidationError
from apps.hardware_requests.workflow_utils import locked_request
from apps.inventory import availability
from apps.makerspaces.guards import require_module


def cancel_request(actor, request, reason):
    """Fence PII before request/box/product locks; commit status, stock and audit once."""
    fenced_tenant_id = request.makerspace_id
    with transaction.atomic():
        assert_mapped_write_allowed(fenced_tenant_id)
        locked = locked_request(request)
        if locked.makerspace_id != fenced_tenant_id:
            raise InvalidTransition("Request makerspace changed; reload the request.")
        if not getattr(actor, "is_authenticated", False):
            raise PermissionDenied("Cancellation requires request review authority.")
        claim_audit_context = getattr(actor, "_claim_audit_context", None)
        # Re-read concrete authority without an actor row lock after the request lock.
        actor = User.objects.filter(pk=getattr(actor, "pk", None)).first()
        if actor is not None and claim_audit_context is not None:
            actor._claim_audit_context = claim_audit_context
        if not (
            getattr(actor, "is_authenticated", False)
            and getattr(actor, "is_active", False)
            and actor.access_status == User.AccessStatus.ACTIVE
            and not getattr(actor, "must_change_password", False)
            and not actor.is_tenant_dump_stub
            and rbac.can(actor, rbac.Action.REJECT_REQUEST, locked.makerspace_id)
        ):
            raise PermissionDenied("Cancellation requires request review authority.")
        require_module(locked.makerspace, "request_workflow")
        if locked.status != HardwareRequest.Status.ACCEPTED:
            raise InvalidTransition("Only accepted, unissued requests can be cancelled.")
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
            raise RequestValidationError("Cancellation reason must contain 1 to 500 characters.")
        _assert_wholly_unissued(locked)

        # Box ownership is released BEFORE products are locked, matching issuance.
        previous_box_id = clear_unissued_assignment(locked)
        availability.release_request_reservation(locked)
        locked.status = HardwareRequest.Status.CANCELLED
        locked.cancellation_reason = reason.strip()
        locked.closed_by = actor
        locked.closed_at = timezone.now()
        locked.save(update_fields=[
            "status", "cancellation_reason", "closed_by", "closed_at", "updated_at",
        ])
        meta = {"reason_recorded": True}
        if previous_box_id is not None:
            meta["previous_box_id"] = previous_box_id
        audit.record(
            actor, "request.cancelled", makerspace=locked.makerspace,
            target=locked, meta=meta,
        )
        notifications.notify_request_cancelled(locked)
        return locked


def _assert_wholly_unissued(request):
    if any(value is not None for value in (
        request.issued_at, request.issued_by_id, request.issue_evidence_id,
    )):
        raise InvalidTransition("Request already has handover evidence or issue history.")
    counters = (
        "issued_quantity", "returned_quantity", "damaged_quantity",
        "missing_quantity", "needs_fix_quantity",
    )
    if any(any(getattr(item, name) != 0 for name in counters) for item in request.items.all()):
        raise InvalidTransition("Request already has handover quantities.")
    if (
        ReturnEvent.objects.filter(request=request).exists()
        or RequesterAccountability.objects.filter(
            Q(request=request) | Q(request_item__request=request)
        ).exists()
        or HardwareRequestItemAsset.objects.filter(request_item__request=request).exists()
        or PublicToolLoan.objects.filter(request=request).exists()
    ):
        raise InvalidTransition("Request already has handover records.")
