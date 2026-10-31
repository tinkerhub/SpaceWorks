"""Public returns reject old reviewed-route damage without spending another loan's stock."""
import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog
from apps.boxes.models import QrScanEvent
from apps.evidence.models import EvidenceUploadFinalization
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem, PublicToolLoan
from apps.hardware_requests.return_helpers import build_resolutions, finalize_return_status
from apps.hardware_requests.self_checkout_workflow import return_tool
from apps.hardware_requests.workflow_errors import ReturnValidationError
from apps.inventory import availability
from tests.atomic_publication.store import png
from tests.loan_return_boundary_helpers import (
    assert_no_settlement_writes, assert_promoted_unattached, assert_unpromoted, boundary_snapshot, buckets,
    change_after_finalization, checkout_direct, checkout_public, make_boundary_lab, resolutions, uploaded_photo,
)
from tests.return_helpers import authenticated_client
from tests.test_public_self_checkout import eligible_member, return_url

pytestmark = pytest.mark.django_db


def _two_public_loans(monkeypatch, settings):
    lab = make_boundary_lab(monkeypatch, settings)
    bad, qrs = checkout_public(lab)
    other_user = eligible_member(lab.space, "unrelated-boundary-borrower")
    other = checkout_direct(lab, borrower=other_user, quantity=1)
    assert buckets(lab.product) == (6, 0, 2, 0, 0, 0)
    return lab, bad, qrs[0], other, None


def _historical_reviewed_resolution(lab, loan, outcome):
    """Reconstruct the old bug's ledger projection, never a supported return API.

    Before HW001 the reviewed route resolved stock/request items while leaving the
    PublicToolLoan checked out. Use the actual resolution and availability math to
    build that historical state; no guard is disabled and no counters are invented.
    """
    with transaction.atomic():
        request = HardwareRequest.objects.select_for_update().get(pk=loan.request_id)
        item = request.items.get()
        resolved = build_resolutions(request, [{
            "item_id": item.pk, "returned": 0,
            "damaged": int(outcome == "damaged"), "missing": int(outcome == "missing"),
        }])
        availability.return_items(request, resolved)
        finalize_return_status(request, lab.actor)
    item.refresh_from_db()
    request.refresh_from_db()
    loan.refresh_from_db()
    assert item.returned_quantity == 0
    assert item.damaged_quantity + item.missing_quantity == item.issued_quantity == 1
    assert request.status == HardwareRequest.Status.CLOSED_WITH_ISSUE
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT


def _return_unrelated_loan(lab, bad, other, qr):
    """A rejection must leave the other borrower's entire real loan returnable."""
    bad_rows = (
        list(HardwareRequest.objects.filter(pk=bad.request_id).values()),
        list(HardwareRequestItem.objects.filter(request_id=bad.request_id).values()),
        list(PublicToolLoan.objects.filter(pk=bad.pk).values()),
    )
    before = buckets(lab.product)
    other_item = other.request.items.get()
    assert other.status == PublicToolLoan.Status.CHECKED_OUT
    assert other_item.issued_quantity == 1 and other_item.returned_quantity == 0
    evidence = uploaded_photo(lab)

    response = lab.client.post(f"/api/v1/admin/direct-loans/{other.pk}/return", {
        "evidence_id": evidence.pk, "notes": "Unrelated tool checked in.",
        "resolutions": resolutions(other.request),
    }, format="json")
    assert response.status_code == 200, response.data
    result = PublicToolLoan.objects.get(pk=other.pk)

    assert result.pk == other.pk and result.status == PublicToolLoan.Status.RETURNED
    other_item.refresh_from_db()
    result.request.refresh_from_db()
    assert other_item.returned_quantity == other_item.issued_quantity == 1
    assert result.request.status == HardwareRequest.Status.RETURNED
    assert result.return_evidence_id == evidence.pk
    assert EvidenceUploadFinalization.objects.get(evidence=evidence).quota_charged
    assert buckets(lab.product) == (before[0] + 1, before[1], before[2] - 1, *before[3:])
    assert bad_rows == (
        list(HardwareRequest.objects.filter(pk=bad.request_id).values()),
        list(HardwareRequestItem.objects.filter(request_id=bad.request_id).values()),
        list(PublicToolLoan.objects.filter(pk=bad.pk).values()),
    )


@pytest.mark.parametrize("outcome", ["damaged", "missing"], ids=["legacy-damaged", "legacy-lost"])
def test_public_return_refuses_historical_reviewed_resolution(monkeypatch, settings, outcome):
    lab, bad, qr, other, other_qr = _two_public_loans(monkeypatch, settings)
    _historical_reviewed_resolution(lab, bad, outcome)
    expected = (6, 0, 1, int(outcome == "damaged"), int(outcome == "missing"), 0)
    assert buckets(lab.product) == expected
    # Enough issued stock remains for the old bug to wrongly debit it a second time.
    assert lab.product.issued_quantity >= bad.request.items.get().issued_quantity
    evidence = uploaded_photo(lab, actor=lab.borrower)
    before, calls = boundary_snapshot(lab), list(lab.store.calls)

    response = authenticated_client(lab.borrower).post(return_url(lab.space), {
        "payload": qr.payload, "evidence_id": evidence.pk, "remark": "Attempted second settlement.",
    }, format="json")

    assert response.status_code == 400, response.data
    assert response.data["code"] == "return_validation_error"
    assert "no longer recorded as fully checked out" in str(response.data["detail"])
    assert_unpromoted(lab, evidence, before, calls)
    _return_unrelated_loan(lab, bad, other, other_qr)


def _corrupt_backing_ledger(loan, variant):
    """Deliberate historical inconsistencies; never used by a happy-path fixture."""
    if variant == "status-only":
        HardwareRequest.objects.filter(pk=loan.request_id).update(status=HardwareRequest.Status.RETURNED)
    else:
        changes = {
            "returned-only": {"returned_quantity": 1},
            "needs-fix-only": {"needs_fix_quantity": 1},
            "accepted-mismatch": {"accepted_quantity": 0},
        }
        HardwareRequestItem.objects.filter(request_id=loan.request_id).update(**changes[variant])


@pytest.mark.parametrize("variant", ["status-only", "returned-only", "needs-fix-only", "accepted-mismatch"])
def test_public_return_service_refuses_inconsistent_backing_ledger(monkeypatch, settings, variant):
    lab, bad, qr, other, other_qr = _two_public_loans(monkeypatch, settings)
    _corrupt_backing_ledger(bad, variant)
    evidence = uploaded_photo(lab, actor=lab.borrower)
    before, calls = boundary_snapshot(lab), list(lab.store.calls)

    with pytest.raises(ReturnValidationError, match="no longer recorded as fully checked out"):
        return_tool(lab.space, lab.borrower, qr.payload,
                    evidence_id=evidence.pk, remark="Check legacy ledger.")

    assert_unpromoted(lab, evidence, before, calls)
    _return_unrelated_loan(lab, bad, other, other_qr)


@pytest.mark.parametrize("variant", ["status-only", "returned-only"])
def test_public_return_rechecks_ledger_after_real_promotion(monkeypatch, settings, variant):
    lab, bad, qr, other, other_qr = _two_public_loans(monkeypatch, settings)
    evidence = uploaded_photo(lab, actor=lab.borrower)
    with CaptureQueriesContext(connection) as queries:
        observed = change_after_finalization(
            monkeypatch, lab, evidence, lambda: _corrupt_backing_ledger(bad, variant), queries,
        )
        with pytest.raises(ReturnValidationError, match="no longer recorded as fully checked out"):
            return_tool(lab.space, lab.borrower, qr.payload,
                        evidence_id=evidence.pk, remark="State changed during storage I/O.")

    assert len(observed) == 1
    assert_no_settlement_writes(queries.captured_queries[observed[0]["query_offset"]:])
    assert boundary_snapshot(lab, finalizations=False) == observed[0]["state"]
    assert_promoted_unattached(lab, evidence)
    _return_unrelated_loan(lab, bad, other, other_qr)


@pytest.mark.parametrize("report_problem", [False, True], ids=["normal", "problem-report"])
def test_canonical_secondary_qr_returns_whole_batch_exactly_once(monkeypatch, settings, report_problem):
    lab = make_boundary_lab(monkeypatch, settings)
    loan, qrs = checkout_public(lab, count=2)
    evidence = uploaded_photo(lab, actor=lab.borrower)
    lab.space.refresh_from_db()
    charged_before = lab.space.storage_bytes_used
    for product in lab.batch_products:
        assert buckets(product) == (7, 0, 1, 0, 0, 0)

    response = authenticated_client(lab.borrower).post(return_url(lab.space), {
        "payload": qrs[1].payload, "evidence_id": evidence.pk, "remark": "Returned entire batch.",
        "report_problem": report_problem, "problem_note": "Intermittent switch." if report_problem else "",
    }, format="json")

    assert response.status_code == 200, response.data
    loan.refresh_from_db()
    loan.request.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.RETURNED and loan.return_evidence_id == evidence.pk
    assert loan.request.status == HardwareRequest.Status.RETURNED
    items = list(loan.request.items.all())
    assert len(items) == 2
    assert all(item.returned_quantity == item.issued_quantity == 1 for item in items)
    for product in lab.batch_products:
        assert buckets(product) == (8, 0, 0, 0, 0, 0)
    assert list(QrScanEvent.objects.filter(request=loan.request, context="return").values_list(
        "qr_code_id", "actor_id",
    )) == [(qrs[1].pk, lab.borrower.pk)]
    assert AuditLog.objects.filter(
        makerspace=lab.space, action="public_tool.returned", target_id=str(loan.request_id),
    ).count() == 1
    assert loan.problem_reports.count() == int(report_problem)
    if report_problem:
        report = loan.problem_reports.get()
        assert report.note == "Intermittent switch." and report.requester_id == lab.borrower.pk
        assert report.resolved_at is None and report.outcome == ""
    lab.space.refresh_from_db()
    assert lab.space.storage_bytes_used == charged_before + len(png())
    assert EvidenceUploadFinalization.objects.get(evidence=evidence).quota_charged

    # A fresh photo rules out evidence-reuse rejection masking a double return.
    replay = uploaded_photo(lab, actor=lab.borrower)
    before, calls = boundary_snapshot(lab), list(lab.store.calls)
    response = authenticated_client(lab.borrower).post(return_url(lab.space), {
        "payload": qrs[0].payload, "evidence_id": replay.pk, "remark": "Duplicate return.",
    }, format="json")
    assert response.status_code == 409, response.data
    assert response.data["code"] == "invalid_transition"
    assert_unpromoted(lab, replay, before, calls)
