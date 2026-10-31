"""One reviewed loan reconciles public availability, staff queues and evidence."""
from copy import deepcopy

import pytest

from apps.audit.models import AuditLog
from apps.boxes.models import BoxScan, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequestItemAsset, ReturnEvent
from apps.inventory.models import InventoryAsset, TrackingMode
from tests.inventory_lending_evidence_helpers import (
    assert_attachment, assert_retained, photo, rejected, retained_rows, uploaded_images,
)
from tests.inventory_lending_helpers import assert_surfaces, make_lab, submit_request
from tests.return_helpers import make_box, return_url
from tests.test_issue import assign_box_url, issue_url
from tests.test_request_workflow import accept_url

pytestmark = pytest.mark.django_db


def _post(lab, url, payload):
    response = lab.client.post(url, payload, format="json")
    assert response.status_code == 200, response.data
    return response.data


def _return_payload(item, evidence, box, asset=None):
    resolution = {"item_id": item.pk, "returned": 1, "damaged": 0, "missing": 0}
    if asset:
        resolution["assets"] = [{"asset_id": asset.pk, "outcome": "returned"}]
    return {
        "evidence_id": evidence.pk, "remark": "Checked physically; good condition.",
        "box_code": box.code if box else "", "resolutions": [resolution],
    }


@pytest.mark.parametrize("tracking_mode", [TrackingMode.QUANTITY, TrackingMode.INDIVIDUAL])
@pytest.mark.parametrize("container", [False, True], ids=["containerless", "assigned-container"])
def test_public_and_staff_counts_follow_reviewed_lifecycle(monkeypatch, settings, tracking_mode, container):
    lab = make_lab(monkeypatch, settings, tracking_mode=tracking_mode)
    store = uploaded_images(monkeypatch, settings)
    loan = submit_request(lab)
    item = loan.items.get()
    assert_surfaces(lab, 3, 0, 0, {loan.pk: "pending_approval"})
    submitted = AuditLog.objects.get(makerspace=lab.space, action="request.submitted", target_id=str(loan.pk))
    assert submitted.actor_id == loan.requester_id
    assert (item.requested_quantity, item.accepted_quantity, item.issued_quantity) == (2, 0, 0)

    _post(lab, accept_url(loan), {"accepted_quantities": [{"item_id": item.pk, "quantity": 2}]})
    assert_surfaces(lab, 1, 2, 0, {loan.pk: "accepted"})
    loan.refresh_from_db()
    assert loan.accepted_by_id == lab.actor.pk and loan.accepted_at is not None
    accepted = AuditLog.objects.get(makerspace=lab.space, action="request.accepted", target_id=str(loan.pk))
    assert accepted.actor_id == lab.actor.pk
    item.refresh_from_db()
    assert item.accepted_quantity == 2 and not item.asset_links.exists()

    box = make_box(lab.space, "Reviewed loan container") if container else None
    if box:
        # Assignment is the canonical issue scan; never fabricate/delete immutable scans.
        rejected(lab, assign_box_url(loan), {})
        rejected(lab, assign_box_url(loan), {"box_code": "wrong-container"}, code="box_validation_error")
        _post(lab, assign_box_url(loan), {"box_code": box.code})
        scan = BoxScan.objects.get(request=loan, context="issue")
        assert (scan.box_id, scan.actor_id, scan.makerspace_id) == (box.pk, lab.actor.pk, lab.space.pk)

    issue_photo = photo(lab, store, "issue")
    return_photo = photo(lab, store, "return")
    absent_photo = photo(lab, store, "issue", uploaded=False)
    issue_data = {
        "evidence_id": issue_photo.pk, "remark": "Handed over two verified units.",
        "asset_qr_payloads": [qr.payload for qr in lab.qrs[:2]],
    }
    rejected(lab, issue_url(loan), {})
    rejected(lab, issue_url(loan), {**issue_data, "evidence_id": return_photo.pk}, code="validation_error")
    rejected(lab, issue_url(loan), {**issue_data, "evidence_id": absent_photo.pk}, 409, "evidence_not_uploaded")
    if lab.assets:
        rejected(lab, issue_url(loan), {**issue_data, "asset_qr_payloads": []}, code="validation_error")
        rejected(lab, issue_url(loan), {
            **issue_data, "asset_qr_payloads": [lab.qrs[0].payload, "wrong-unit-qr"],
        }, code="validation_error")
    durable = retained_rows(lab)
    issued = _post(lab, issue_url(loan), issue_data)
    assert issued["issue_evidence_id"] == issue_photo.pk
    assert_surfaces(lab, 1, 0, 2, {loan.pk: "issued"})
    loan.refresh_from_db()
    item.refresh_from_db()
    assert loan.issue_evidence_id == issue_photo.pk and loan.issued_by_id == lab.actor.pk
    assert loan.issue_remark == issue_data["remark"] and loan.issued_at is not None
    assert item.issued_quantity == 2 and item.returned_quantity == 0
    assert_attachment(lab, loan, issue_photo, "request.issued")
    assert_retained(lab, durable)
    assert issue_photo.object_key in store.objects
    assert f"staging/{issue_photo.object_key}" not in store.objects
    rejected(lab, issue_url(loan), issue_data, 409, "invalid_transition")
    if lab.assets:
        assert set(item.asset_links.values_list("asset_id", "outcome")) == {
            (asset.pk, "issued") for asset in lab.assets[:2]
        }
        assert set(QrScanEvent.objects.filter(request=loan, context="issue").values_list(
            "qr_code_id", "actor_id",
        )) == {(qr.pk, lab.actor.pk) for qr in lab.qrs[:2]}
        lab.assets[2].refresh_from_db()
        assert lab.assets[2].status == InventoryAsset.Status.AVAILABLE
        assert not HardwareRequestItemAsset.objects.filter(asset=lab.assets[2]).exists()
        assert set(AuditLog.objects.filter(
            makerspace=lab.space, action="asset.issued", meta__request_id=loan.pk,
        ).values_list("target_id", "actor_id")) == {
            (str(asset.pk), lab.actor.pk) for asset in lab.assets[:2]
        }

    first_asset = lab.assets[0] if lab.assets else None
    return_data = _return_payload(item, return_photo, box, first_asset)
    missing_photo = deepcopy(return_data)
    del missing_photo["evidence_id"]
    rejected(lab, return_url(loan), missing_photo)
    rejected(lab, return_url(loan), {**return_data, "evidence_id": issue_photo.pk}, code="return_validation_error")
    rejected(lab, return_url(loan), {**return_data, "remark": "  "})
    if box:
        rejected(lab, return_url(loan), {**return_data, "box_code": ""}, code="return_validation_error")
    rejected(lab, return_url(loan), {**return_data, "box_code": "wrong-container"}, code="return_validation_error")
    if lab.assets:
        no_identity = deepcopy(return_data)
        del no_identity["resolutions"][0]["assets"]
        rejected(lab, return_url(loan), no_identity, code="return_validation_error")
        wrong_identity = _return_payload(item, return_photo, box, lab.assets[2])
        rejected(lab, return_url(loan), wrong_identity, code="return_validation_error")

    durable = retained_rows(lab)
    _post(lab, return_url(loan), return_data)
    assert_surfaces(lab, 2, 0, 1, {loan.pk: "partially_returned"})
    assert_attachment(lab, loan, return_photo, "request.partially_returned")
    assert_retained(lab, durable)
    first_event = ReturnEvent.objects.get(request=loan, evidence=return_photo)
    assert (first_event.actor_id, first_event.box_id, first_event.remark) == (
        lab.actor.pk, box.pk if box else None, return_data["remark"],
    )
    item.refresh_from_db()
    assert (item.issued_quantity, item.returned_quantity) == (2, 1)
    if lab.assets:
        first_link = item.asset_links.get(asset=lab.assets[0])
        assert first_link.outcome == "returned" and first_link.return_event_id == first_event.pk
        assert first_link.returned_at is not None
        assert item.asset_links.get(asset=lab.assets[1]).outcome == "issued"
        assert list(InventoryAsset.objects.filter(pk__in=[a.pk for a in lab.assets]).order_by("pk").values_list(
            "status", flat=True,
        )) == ["available", "issued", "available"]

    second_asset = lab.assets[1] if lab.assets else None
    # Reuse with a still-issued unit reaches the real evidence uniqueness guard.
    reused = _return_payload(item, return_photo, box, second_asset)
    rejected(lab, return_url(loan), reused, code="return_validation_error")
    if lab.assets:
        fresh = photo(lab, store, "return")
        rejected(lab, return_url(loan), _return_payload(item, fresh, box, lab.assets[0]), code="return_validation_error")

    final_photo = photo(lab, store, "return")
    final_data = _return_payload(item, final_photo, box, second_asset)
    durable = retained_rows(lab)
    _post(lab, return_url(loan), final_data)
    assert_surfaces(lab, 3, 0, 0, {loan.pk: "returned"})
    assert_attachment(lab, loan, final_photo, "request.returned")
    assert_retained(lab, durable)
    loan.refresh_from_db()
    item.refresh_from_db()
    assert loan.closed_by_id == lab.actor.pk and loan.closed_at is not None
    assert item.returned_quantity == item.issued_quantity == 2
    events = ReturnEvent.objects.filter(request=loan)
    assert set(events.values_list("evidence_id", "actor_id", "box_id")) == {
        (p.pk, lab.actor.pk, box.pk if box else None) for p in [return_photo, final_photo]
    }
    if lab.assets:
        final_event = events.get(evidence=final_photo)
        last_link = item.asset_links.get(asset=lab.assets[1])
        assert last_link.return_event_id == final_event.pk and last_link.returned_at is not None
        assert set(item.asset_links.values_list("outcome", flat=True)) == {"returned"}
        assert set(QrScanEvent.objects.filter(request=loan, context="return").values_list(
            "qr_code_id", "actor_id",
        )) == {(qr.pk, lab.actor.pk) for qr in lab.qrs[:2]}
    else:
        assert not HardwareRequestItemAsset.objects.filter(request_item=item).exists()
        assert not QrScanEvent.objects.filter(request=loan).exists()
    assert BoxScan.objects.filter(request=loan, context="return").count() == (2 if box else 0)
    if box:
        assert list(BoxScan.objects.filter(request=loan, context="return").values_list(
            "box_id", "actor_id", "makerspace_id",
        )) == [(box.pk, lab.actor.pk, lab.space.pk)] * 2
    if not box:
        assert not BoxScan.objects.filter(request=loan).exists()
        assert not AuditLog.objects.filter(makerspace=lab.space, action="box.scanned").exists()
    for evidence in [issue_photo, return_photo, final_photo]:
        evidence.refresh_from_db()
        assert evidence.uploaded_by_id == lab.actor.pk
        assert evidence.makerspace_id == lab.space.pk and evidence.created_at is not None
        assert EvidencePhoto.objects.filter(pk=evidence.pk).exists()
    rejected(lab, return_url(loan), final_data, 409, "invalid_transition")
