"""Reviewed return admission must never settle a PublicToolLoan backing request."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.hardware_requests import workflow
from apps.evidence.models import EvidenceUploadFinalization
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan, ReturnEvent
from apps.hardware_requests.workflow_errors import ReturnValidationError
from tests.loan_return_boundary_helpers import (
    assert_no_settlement_writes, assert_promoted_unattached, assert_unpromoted,
    associate_loan, boundary_snapshot, buckets,
    change_after_finalization, checkout_direct, checkout_public, checkout_reviewed,
    make_boundary_lab, reviewed_body, uploaded_photo,
)
from tests.return_helpers import authenticated_client, make_member, make_space, return_url

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("source", ["public", "direct"])
def test_reviewed_return_api_refuses_real_loan_before_promotion(monkeypatch, settings, source):
    lab = make_boundary_lab(monkeypatch, settings)
    loan = checkout_public(lab)[0] if source == "public" else checkout_direct(lab)
    evidence = uploaded_photo(lab)
    before, calls = boundary_snapshot(lab), list(lab.store.calls)

    response = lab.client.post(return_url(loan.request), reviewed_body(loan.request, evidence), format="json")

    assert response.status_code == 400, response.data
    assert response.data["code"] == "return_validation_error"
    assert "public tool or direct loan return flow" in str(response.data["detail"])
    assert_unpromoted(lab, evidence, before, calls)
    if source == "direct":
        # The rejected photo remains usable by the canonical full direct return.
        returned = lab.client.post(f"/api/v1/admin/direct-loans/{loan.pk}/return", {
            "evidence_id": evidence.pk, "notes": "All units checked at the desk.",
            "resolutions": reviewed_body(loan.request, evidence)["resolutions"],
        }, format="json")
        assert returned.status_code == 200, returned.data
        loan.refresh_from_db()
        loan.request.refresh_from_db()
        assert loan.status == PublicToolLoan.Status.RETURNED
        assert loan.return_evidence_id == evidence.pk
        assert loan.request.status == HardwareRequest.Status.RETURNED
        item = loan.request.items.get()
        assert item.returned_quantity == item.issued_quantity == 2
        assert ReturnEvent.objects.get(request=loan.request).evidence_id == evidence.pk
        assert EvidenceUploadFinalization.objects.get(evidence=evidence).quota_charged
        assert buckets(lab.product) == (8, 0, 0, 0, 0, 0)


@pytest.mark.parametrize("source", ["public", "direct"])
def test_reviewed_return_service_also_refuses_real_loan(monkeypatch, settings, source):
    lab = make_boundary_lab(monkeypatch, settings)
    loan = checkout_public(lab)[0] if source == "public" else checkout_direct(lab)
    evidence = uploaded_photo(lab)
    body = reviewed_body(loan.request, evidence)
    before, calls = boundary_snapshot(lab), list(lab.store.calls)

    with pytest.raises(ReturnValidationError, match="public tool or direct loan return flow"):
        workflow.return_items(lab.actor, loan.request, evidence.pk,
                              body["remark"], body["box_code"], body["resolutions"])

    assert_unpromoted(lab, evidence, before, calls)


@pytest.mark.parametrize("caller,status", [("member", 403), ("foreign-manager", 404)])
def test_reviewed_return_keeps_permission_and_tenant_boundary(monkeypatch, settings, caller, status):
    lab = make_boundary_lab(monkeypatch, settings)
    loan, _ = checkout_public(lab)
    actor = lab.borrower if caller == "member" else make_member(
        "foreign-return-manager", make_space("foreign-return-space"),
    )
    evidence = uploaded_photo(lab)
    before, calls = boundary_snapshot(lab), list(lab.store.calls)

    response = authenticated_client(actor).post(
        return_url(loan.request), reviewed_body(loan.request, evidence), format="json",
    )

    assert response.status_code == status, response.data
    if status == 404:
        assert response.data["detail"].code == "not_found"
    assert_unpromoted(lab, evidence, before, calls)


def test_reviewed_return_does_not_trust_cached_absent_loan(monkeypatch, settings):
    lab = make_boundary_lab(monkeypatch, settings)
    request = checkout_reviewed(lab)
    stale = HardwareRequest.objects.select_related("public_tool_loan").get(pk=request.pk)
    # Cache a missing reverse OneToOne before an association appears in storage.
    with pytest.raises(HardwareRequest.public_tool_loan.RelatedObjectDoesNotExist):
        _ = stale.public_tool_loan
    associate_loan(request)
    evidence = uploaded_photo(lab)
    body = reviewed_body(request, evidence)
    before, calls = boundary_snapshot(lab), list(lab.store.calls)

    with pytest.raises(ReturnValidationError, match="public tool or direct loan return flow"):
        workflow.return_items(lab.actor, stale, evidence.pk, body["remark"], "", body["resolutions"])

    assert_unpromoted(lab, evidence, before, calls)


def test_reviewed_return_rechecks_association_after_real_promotion(monkeypatch, settings):
    lab = make_boundary_lab(monkeypatch, settings)
    request = checkout_reviewed(lab)
    evidence = uploaded_photo(lab)
    body = reviewed_body(request, evidence)
    with CaptureQueriesContext(connection) as queries:
        observed = change_after_finalization(
            monkeypatch, lab, evidence, lambda: associate_loan(request), queries,
        )
        with pytest.raises(ReturnValidationError, match="public tool or direct loan return flow"):
            workflow.return_items(lab.actor, request, evidence.pk, body["remark"], "", body["resolutions"])

    assert len(observed) == 1  # Passed initial admission and real image promotion.
    assert_no_settlement_writes(queries.captured_queries[observed[0]["query_offset"]:])
    assert boundary_snapshot(lab, finalizations=False) == observed[0]["state"]
    assert_promoted_unattached(lab, evidence)
