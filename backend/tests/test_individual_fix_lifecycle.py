"""Unit repair and protected reservations remain compatible with real handover."""
import pytest

from apps.audit.models import AuditLog
from apps.boxes.models import BoxScan, QrScanEvent
from apps.hardware_requests.models import HardwareRequestItemAsset, ReturnEvent
from apps.inventory.models import InventoryAsset, TrackingMode
from tests.inventory_lending_evidence_helpers import (
    assert_attachment, assert_retained, photo, retained_rows, uploaded_images,
)
from tests.inventory_lending_helpers import assert_surfaces, make_lab, submit_request
from tests.return_helpers import return_url
from tests.test_individual_fix_boundaries import fix_snapshot, fix_url, park_unit
from tests.test_issue import issue_url
from tests.test_request_workflow import accept_url

pytestmark = pytest.mark.django_db


def post_ok(lab, url, payload):
    response = lab.client.post(url, payload, format="json")
    assert response.status_code == 200, response.data
    return response


def accept_one(lab):
    loan = submit_request(lab, quantity=1)
    post_ok(lab, accept_url(loan), {})
    assert_surfaces(lab, 0, 1, 0, {loan.pk: "accepted"})
    return loan


def issue_payload(lab, evidence):
    return {
        "evidence_id": evidence.pk, "remark": "Verified repaired unit at handover.",
        "asset_qr_payloads": [lab.qrs[0].payload],
    }


def assert_issued_trace(lab, loan, evidence):
    assert_surfaces(lab, 0, 0, 1, {loan.pk: "issued"})
    loan.refresh_from_db()
    assert loan.assigned_box_id is None and loan.issue_evidence_id == evidence.pk
    assert loan.issued_by_id == lab.actor.pk and loan.issued_at is not None
    assert loan.issue_remark == issue_payload(lab, evidence)["remark"]
    item = loan.items.get()
    assert (item.accepted_quantity, item.issued_quantity, item.returned_quantity) == (1, 1, 0)
    link = HardwareRequestItemAsset.objects.get(request_item=item)
    assert link.asset_id == lab.assets[0].pk and link.outcome == "issued"
    assert link.return_event_id is None
    scan = QrScanEvent.objects.get(request=loan, context="issue")
    assert (scan.qr_code_id, scan.actor_id) == (lab.qrs[0].pk, lab.actor.pk)
    event = AuditLog.objects.get(
        makerspace=lab.space, action="asset.issued", target_id=str(lab.assets[0].pk),
    )
    assert event.actor_id == lab.actor.pk
    assert event.meta == {"request_id": loan.pk, "request_item_id": item.pk, "qr_id": lab.qrs[0].pk}
    assert_attachment(lab, loan, evidence, "request.issued")


def return_one(lab, loan, store):
    evidence = photo(lab, store, "return")
    durable = retained_rows(lab)
    post_ok(lab, return_url(loan), {
        "evidence_id": evidence.pk, "remark": "Physically checked; repaired unit is sound.",
        "box_code": "", "resolutions": [{
            "item_id": loan.items.get().pk, "returned": 1, "damaged": 0, "missing": 0,
            "assets": [{"asset_id": lab.assets[0].pk, "outcome": "returned"}],
        }],
    })
    assert_surfaces(lab, 1, 0, 0, {loan.pk: "returned"})
    event = ReturnEvent.objects.get(request=loan)
    assert event.evidence_id == evidence.pk and event.actor_id == lab.actor.pk
    assert event.box_id is None and event.remark == "Physically checked; repaired unit is sound."
    link = loan.items.get().asset_links.get()
    assert link.asset_id == lab.assets[0].pk and link.outcome == "returned"
    assert link.return_event_id == event.pk and link.returned_at is not None
    scan = QrScanEvent.objects.get(request=loan, context="return")
    assert (scan.qr_code_id, scan.actor_id) == (lab.qrs[0].pk, lab.actor.pk)
    assert not BoxScan.objects.filter(request=loan).exists()
    assert_attachment(lab, loan, evidence, "request.returned")
    assert_retained(lab, durable)


def test_repaired_unit_reconciles_surfaces_and_completes_real_lending_cycle(monkeypatch, settings):
    lab = make_lab(monkeypatch, settings, total=1, tracking_mode=TrackingMode.INDIVIDUAL)
    store = uploaded_images(monkeypatch, settings)
    park_unit(lab)
    public = lab.public.get(f"/api/v1/public/{lab.space.slug}/inventory/{lab.product.pk}/")
    assert public.status_code == 200
    assert public.data["availability"] == {"mode": "exact_count", "count": 0, "label": "Unavailable"}
    staff = lab.client.get(f"/api/v1/admin/inventory/{lab.product.pk}")
    assert staff.status_code == 200
    assert (staff.data["available_quantity"], staff.data["needs_fix_quantity"]) == (0, 1)

    repaired = post_ok(lab, fix_url(lab.assets[0]), {"action": "repair"})
    assert repaired.data["status"] == "available"
    assert_surfaces(lab, 1, 0, 0, {})
    entry = AuditLog.objects.get(makerspace=lab.space, action="inventory.asset_needs_fix_repair")
    assert entry.target_id == str(lab.assets[0].pk) and entry.actor_id == lab.actor.pk
    assert entry.meta == {"product_id": lab.product.pk, "asset_tag": lab.assets[0].asset_tag}
    durable = retained_rows(lab)
    loan = accept_one(lab)
    evidence = photo(lab, store, "issue")
    post_ok(lab, issue_url(loan), issue_payload(lab, evidence))
    assert_issued_trace(lab, loan, evidence)
    assert_retained(lab, durable)
    return_one(lab, loan, store)


def test_unmarked_accepted_reservation_refuses_shelve_then_issues_normally(monkeypatch, settings):
    lab = make_lab(monkeypatch, settings, total=1, tracking_mode=TrackingMode.INDIVIDUAL)
    store = uploaded_images(monkeypatch, settings)
    loan = accept_one(lab)
    lab.assets[0].refresh_from_db()
    assert lab.assets[0].status == InventoryAsset.Status.AVAILABLE
    assert not loan.items.get().asset_links.exists()
    before = fix_snapshot(lab)

    response = lab.client.post(fix_url(lab.assets[0]), {"action": "shelve"}, format="json")

    assert response.status_code == 400, response.data
    # Canonical move_asset_status reconciles AVAILABLE rows minus the reservation;
    # it has no available bucket stock to move. Do not invent parallel stock math.
    assert "no available_quantity stock to move" in str(response.data)
    assert fix_snapshot(lab) == before
    assert_surfaces(lab, 0, 1, 0, {loan.pk: "accepted"})
    evidence = photo(lab, store, "issue")
    post_ok(lab, issue_url(loan), issue_payload(lab, evidence))
    assert_issued_trace(lab, loan, evidence)
    return_one(lab, loan, store)
