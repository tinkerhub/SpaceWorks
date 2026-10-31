"""Admission checks for the all-at-once public self-checkout return contract."""

from django.db.models import Q

from apps.boxes.models import QrCode
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem, PublicToolLoan
from apps.hardware_requests.workflow_errors import (
    InvalidTransition,
    RequestValidationError,
    RequesterBlocked,
    ReturnValidationError,
)


def preflight_public_return(makerspace, requester, payload) -> None:
    """Reject invalid returns before S3 I/O; these unlocked rows never authorize settlement."""
    qr = QrCode.objects.filter(
        payload=payload, makerspace=makerspace, status=QrCode.Status.ACTIVE
    ).first()
    if qr is None:
        raise RequestValidationError("QR code is not active for this makerspace.")
    loan = (
        PublicToolLoan.objects.select_related("request")
        .filter(
            makerspace=makerspace,
            status=PublicToolLoan.Status.CHECKED_OUT,
            source=PublicToolLoan.Source.PUBLIC_SELF_CHECKOUT,
        )
        .filter(Q(qr_code=qr) | Q(qr_ids__contains=[qr.id]))
        .first()
    )
    if loan is None:
        raise InvalidTransition("This QR code is not currently checked out.")
    if loan.requester_id != requester.id:
        raise RequesterBlocked("This tool was checked out by a different user.")
    require_public_return_ledger(loan)


def require_public_return_ledger(loan: PublicToolLoan, *, lock_items: bool = False) -> None:
    """Require the producer's full, unresolved ledger; locked callers hold loan + request.

    Public checkout creates equal requested/accepted/issued quantities. Public return
    resolves the entire batch, even through a secondary QR, so any prior resolution
    is inconsistent. Read item rows afresh rather than trusting a related-object cache.
    """
    request = loan.request
    items = HardwareRequestItem.objects.filter(request_id=request.pk).order_by("pk")
    if lock_items:
        items = items.select_for_update()
    items = list(items)
    if (
        request.makerspace_id != loan.makerspace_id
        or request.requester_id != loan.requester_id
        or request.status != HardwareRequest.Status.ISSUED
        or not items
        or any(
            item.issued_quantity <= 0
            or item.requested_quantity != item.issued_quantity
            or item.accepted_quantity != item.issued_quantity
            or item.returned_quantity != 0
            or item.damaged_quantity != 0
            or item.missing_quantity != 0
            or item.needs_fix_quantity != 0
            for item in items
        )
    ):
        raise ReturnValidationError(
            "This loan is no longer recorded as fully checked out; ask staff to "
            "reconcile its return history."
        )
