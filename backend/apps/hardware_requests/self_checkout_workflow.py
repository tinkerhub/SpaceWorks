from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.boxes.models import QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.evidence.finalization import charge_storage_once
from apps.hardware_requests.models import (
    HardwareRequest,
    PublicProblemReport,
    PublicToolLoan,
    ReturnEvent,
)
from apps.hardware_requests.self_checkout_helpers import (
    _checkout_target,
    _issued_request,
    _locked_qr,
    _locked_qrs_for_payloads,
    _reject_overlapping_checkout_targets,
    _return_request_items,
)
from apps.hardware_requests.workflow_errors import (
    InvalidTransition,
    RequestValidationError,
    RequesterBlocked,
    ReturnValidationError,
)
from apps.hardware_requests.direct_loan_returns import validate_evidence_upload
from apps.inventory.models import InventoryAsset
from apps.makerspaces.guards import require_feature, require_feature_locked
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import is_servable
from apps.notifications.emit import emit_notification


def checkout_tool(
    makerspace,
    requester,
    payload=None,
    *,
    qr_payloads=None,
    evidence_id,
    remark="",
):
    if payload is not None and qr_payloads:
        raise RequestValidationError("Provide either payload or qr_payloads, not both.")
    payloads = list(qr_payloads or ([] if payload is None else [payload]))
    if not payloads:
        raise RequestValidationError("Provide payload or qr_payloads.")
    # Gate on the feature and on servability BEFORE touching evidence. Promotion moved
    # out of the transaction so its row locks never span S3 I/O, and moving the evidence
    # work up with it put it ahead of the feature check -- so a makerspace with
    # self-checkout disabled reported an evidence error instead of the feature error, and
    # promoted an upload on the way there. The locked recheck below is still the
    # authority; this is the cheap pre-check that keeps the ordering honest.
    # By pk, not by the instance the caller handed us: require_feature() trusts a
    # Makerspace argument as-is, so a stale in-memory copy would pass a gate the stored
    # row has already closed.
    current = require_feature(makerspace.pk, "inventory.self_checkout")
    if not is_servable(current):
        raise RequestValidationError("Makerspace is not available.")
    evidence = _public_evidence(
        makerspace, requester, evidence_id, EvidencePhoto.EvidenceType.ISSUE
    )
    finalized = validate_evidence_upload(evidence, label="Issue")
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        makerspace = require_feature_locked(makerspace, "inventory.self_checkout")
        if not is_servable(makerspace):
            raise RequestValidationError("Makerspace is not available.")
        due_at = timezone.now() + timedelta(days=(makerspace.default_loan_days or 7))
        _lock_unused_evidence(evidence, issue=True)
        qrs = _locked_qrs_for_payloads(makerspace, payloads)
        if len({qr.id for qr in qrs}) != len(qrs):
            raise InvalidTransition("The same QR code was scanned more than once.")
        _reject_overlapping_checkout_targets(qrs)
        if any(qr_has_active_loan(makerspace, qr) for qr in qrs):
            raise InvalidTransition("This QR code is already checked out.")

        charge_storage_once(evidence, finalized.size)
        product_quantities = Counter()
        asset_ids = []
        labels = []
        container = None
        for qr in qrs:
            label, quantities, target_asset_ids, target_container = _checkout_target(qr)
            if target_container is not None:
                if container is None:
                    container = target_container
                elif container.id != target_container.id:
                    raise InvalidTransition(
                        "Only one handout container can be checked out at a time."
                    )
            labels.append(label)
            product_quantities.update(quantities)
            asset_ids.extend(target_asset_ids)

        first_qr = qrs[0]
        target_label = ", ".join(labels)[:200]
        hardware_request = _issued_request(
            makerspace,
            requester,
            requester.username,
            dict(product_quantities),
            requester_name=requester.display_name,
            contact_email=requester.email,
            contact_phone=requester.phone,
            return_due_at=due_at,
        )
        hardware_request.issue_evidence = evidence
        hardware_request.issue_remark = str(remark or "").strip()
        hardware_request.save(update_fields=["issue_evidence", "issue_remark", "updated_at"])
        loan = PublicToolLoan.objects.create(
            makerspace=makerspace,
            qr_code=first_qr,
            qr_ids=[qr.id for qr in qrs],
            container=container,
            request=hardware_request,
            requester=requester,
            target_type=first_qr.target_type,
            target_id=first_qr.target_id,
            target_label=target_label,
            asset_ids=asset_ids,
            due_at=due_at,
        )
        for qr in qrs:
            QrScanEvent.objects.create(
                makerspace=makerspace,
                qr_code=qr,
                actor=requester,
                context=QrScanEvent.Context.ISSUE,
                request=hardware_request,
            )
        audit.record(
            requester,
            "public_tool.checked_out",
            makerspace=makerspace,
            target=hardware_request,
            meta={"qr_id": first_qr.id, "target": target_label},
        )
        return loan


def return_tool(
    makerspace,
    requester,
    payload,
    *,
    evidence_id,
    remark,
    report_problem=False,
    problem_note="",
):
    remark = str(remark or "").strip()
    if not remark:
        raise RequestValidationError("Return remark is required.")
    # Same ordering rule as checkout_tool: an unservable makerspace must not reach
    # evidence handling. Re-read for the same stale-instance reason; the locked recheck
    # inside the transaction remains the authority.
    if not is_servable(Makerspace.objects.get(pk=makerspace.pk)):
        raise RequestValidationError("Makerspace is not available.")
    evidence = _public_evidence(
        makerspace, requester, evidence_id, EvidencePhoto.EvidenceType.RETURN
    )
    finalized = validate_evidence_upload(evidence, label="Return")
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if not is_servable(makerspace):
            raise RequestValidationError("Makerspace is not available.")
        _lock_unused_evidence(evidence, issue=False)
        charge_storage_once(evidence, finalized.size)
        qr = _locked_qr(makerspace, payload)
        loan = (
            PublicToolLoan.objects.select_for_update()
            .select_related("request", "requester")
            .filter(status=PublicToolLoan.Status.CHECKED_OUT)
            .filter(Q(qr_code=qr) | Q(qr_ids__contains=[qr.id]))
            .first()
        )
        if loan is None:
            raise InvalidTransition("This QR code is not currently checked out.")
        if loan.requester_id != requester.id:
            raise RequesterBlocked("This tool was checked out by a different user.")

        _return_request_items(loan.request)
        if loan.asset_ids:
            InventoryAsset.objects.select_for_update().filter(
                pk__in=loan.asset_ids,
                makerspace=makerspace,
            ).update(status=InventoryAsset.Status.AVAILABLE)

        loan.status = PublicToolLoan.Status.RETURNED
        loan.returned_at = timezone.now()
        loan.return_evidence = evidence
        loan.return_notes = remark
        loan.save(update_fields=["status", "returned_at", "return_evidence", "return_notes"])
        loan.request.status = HardwareRequest.Status.RETURNED
        loan.request.closed_by = requester
        loan.request.closed_at = loan.returned_at
        loan.request.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])
        QrScanEvent.objects.create(
            makerspace=makerspace,
            qr_code=qr,
            actor=requester,
            context=QrScanEvent.Context.RETURN,
            request=loan.request,
        )
        audit.record(
            requester,
            "public_tool.returned",
            makerspace=makerspace,
            target=loan.request,
            meta={"qr_id": qr.id, "target": loan.target_label},
        )
        if report_problem:
            report = PublicProblemReport.objects.create(
                makerspace=makerspace,
                loan=loan,
                request=loan.request,
                requester=requester,
                note=problem_note.strip(),
            )
            audit.record(
                requester,
                "public_tool.problem_reported",
                makerspace=makerspace,
                target=report,
                meta={"loan_id": loan.pk, "request_id": loan.request_id},
            )
            emit_notification(
                makerspace,
                level="warning",
                event="problem_report.filed",
                title="Tool problem reported",
                body=f"Problem report #{report.pk} filed for loan #{loan.pk}.",
            )
        return loan


def _public_evidence(makerspace, requester, evidence_id, evidence_type):
    evidence = EvidencePhoto.objects.filter(
        pk=evidence_id,
        makerspace=makerspace,
        evidence_type=evidence_type,
        uploaded_by=requester,
    ).first()
    if evidence is None:
        raise RequestValidationError("Invalid evidence.")
    return evidence


def _lock_unused_evidence(evidence, *, issue):
    EvidencePhoto.objects.select_for_update().get(pk=evidence.pk)
    if issue:
        if HardwareRequest.objects.filter(issue_evidence=evidence).exists():
            raise RequestValidationError("Evidence already used.")
        return
    if (
        PublicToolLoan.objects.filter(return_evidence=evidence).exists()
        or ReturnEvent.objects.filter(evidence=evidence).exists()
    ):
        raise ReturnValidationError("Evidence already used.")


def qr_has_active_loan(makerspace, qr):
    """True if this QR is part of any currently checked-out loan.

    A direct handout can bundle several QRs onto one loan; only the first lands in
    the `qr_code` FK (the partial-unique constraint allows just one), so the rest
    are tracked in `qr_ids`. Checking both closes the re-issue gap where a
    secondary QR looked free. Callers hold the relevant QR row lock(s), so the
    check is race-free against concurrent checkouts of the same QR."""
    return (
        PublicToolLoan.objects.filter(
            makerspace=makerspace,
            status=PublicToolLoan.Status.CHECKED_OUT,
        )
        .filter(Q(qr_code=qr) | Q(qr_ids__contains=[qr.id]))
        .exists()
    )
