"""Reviewed handovers keep their evidence/stock trail with or without a container."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.audit.models import AuditLog
from apps.boxes.models import BoxScan, QrCode, QrScanEvent
from apps.evidence.models import EvidenceUploadFinalization
from apps.hardware_requests.models import (
    HardwareRequest, HardwareRequestItem, HardwareRequestItemAsset, ReturnEvent,
)
from apps.inventory.models import InventoryAsset, TrackingMode
from tests.handout_roles import make_handout_member
from tests.return_helpers import make_print_manager, make_return_evidence, return_url
from tests.test_issue import (
    active_loans_url, assign_box_url, authenticated_client, issue_payload, issue_url,
    make_box, make_issue_evidence, make_member, make_product, make_space, make_user,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def accepted(request, monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "post"
    exists = Mock(return_value=True)
    monkeypatch.setattr("apps.evidence.storage.object_exists", exists)
    monkeypatch.setattr("apps.evidence.storage.delete_object", Mock())
    mode = getattr(request, "param", TrackingMode.QUANTITY)
    space = make_space("containerless")
    reviewer = make_member("reviewer", space)
    actor = make_handout_member("handover", space)
    product = make_product(space, tracking_mode=mode, total_quantity=2, available_quantity=2)
    assets = []
    qrs = []
    if mode == TrackingMode.INDIVIDUAL:
        for index in range(2):
            asset = InventoryAsset.objects.create(
                makerspace=space, product=product, asset_tag=f"SCOPE-{index}",
            )
            assets.append(asset)
            qrs.append(QrCode.objects.create(
                makerspace=space, target_type=QrCode.TargetType.ASSET, target_id=asset.pk,
            ))
    requester = make_user("borrower")
    loan = HardwareRequest.objects.create(
        makerspace=space, requester=requester, requester_username=requester.username,
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    item = HardwareRequestItem.objects.create(request=loan, product=product, requested_quantity=2)
    response = authenticated_client(reviewer).post(
        f"/api/v1/admin/requests/{loan.pk}/accept",
        {"accepted_quantities": [{"item_id": item.pk, "quantity": 2}]}, format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["assigned_box_id"] is None
    loan.refresh_from_db()
    item.refresh_from_db()
    assert loan.status == HardwareRequest.Status.ACCEPTED
    assert item.accepted_quantity == 2
    assert_stock(product, 0, 2, 0)
    return SimpleNamespace(
        space=space, actor=actor, product=product, loan=loan, item=item,
        assets=assets, qrs=qrs, exists=exists, client=authenticated_client(actor),
    )


def assert_stock(product, available, reserved, issued):
    product.refresh_from_db()
    assert (product.available_quantity, product.reserved_quantity, product.issued_quantity) == (
        available, reserved, issued,
    )
    assert (product.total_quantity, product.damaged_quantity, product.lost_quantity) == (2, 0, 0)


def issue(accepted):
    evidence = make_issue_evidence(accepted.space, accepted.actor)
    response = accepted.client.post(issue_url(accepted.loan), {
        **issue_payload(evidence), "asset_qr_payloads": [qr.payload for qr in accepted.qrs],
    }, format="json")
    assert response.status_code == 200, response.data
    assert response.data["assigned_box_id"] is None
    return evidence


def return_data(accepted, evidence, asset=None):
    resolution = {"item_id": accepted.item.pk, "returned": 1, "damaged": 0, "missing": 0}
    if asset is not None:
        resolution["assets"] = [{"asset_id": asset.pk, "outcome": "returned"}]
    return {"evidence_id": evidence.pk, "remark": "Checked on return.", "resolutions": [resolution]}


def domain_snapshot(accepted):
    """Rejections may finalize uploaded bytes, but may not consume or move hardware."""
    return {
        "request": HardwareRequest.objects.filter(pk=accepted.loan.pk).values(
            "status", "assigned_box_id", "issue_evidence_id", "issued_at", "closed_at",
        ).get(),
        "stock": type(accepted.product).objects.filter(pk=accepted.product.pk).values(
            "available_quantity", "reserved_quantity", "issued_quantity", "damaged_quantity", "lost_quantity",
        ).get(),
        "item": HardwareRequestItem.objects.filter(pk=accepted.item.pk).values(
            "issued_quantity", "returned_quantity", "damaged_quantity", "missing_quantity",
        ).get(),
        "assets": list(InventoryAsset.objects.filter(product=accepted.product).values_list("pk", "status")),
        "links": list(HardwareRequestItemAsset.objects.filter(request_item=accepted.item).values_list("pk", "outcome")),
        "events": ReturnEvent.objects.filter(request=accepted.loan).count(),
        "box_scans": BoxScan.objects.filter(request=accepted.loan).count(),
        "qr_scans": QrScanEvent.objects.filter(request=accepted.loan).count(),
        "audit": AuditLog.objects.count(),
    }


@pytest.mark.parametrize("accepted", [TrackingMode.QUANTITY, TrackingMode.INDIVIDUAL], indirect=True)
def test_containerless_issue_partial_and_full_return_preserve_traceability(accepted):
    photo = issue(accepted)
    loan, item = accepted.loan, accepted.item
    loan.refresh_from_db()
    item.refresh_from_db()
    assert loan.status == HardwareRequest.Status.ISSUED
    assert loan.issue_evidence_id == photo.pk
    assert item.issued_quantity == 2
    assert_stock(accepted.product, 0, 0, 2)
    if accepted.assets:
        assert set(item.asset_links.values_list("asset_id", "outcome")) == {
            (asset.pk, HardwareRequestItemAsset.Outcome.ISSUED) for asset in accepted.assets
        }
        assert set(InventoryAsset.objects.values_list("status", flat=True)) == {InventoryAsset.Status.ISSUED}
        assert set(QrScanEvent.objects.filter(request=loan, context="issue").values_list("qr_code_id", flat=True)) == {
            qr.pk for qr in accepted.qrs
        }

    loans = accepted.client.get(active_loans_url(accepted.space))
    assert loans.status_code == 200
    assert loans.data["results"][0]["assigned_box_id"] is None
    photos = [photo]
    for index, state in enumerate([HardwareRequest.Status.PARTIALLY_RETURNED, HardwareRequest.Status.RETURNED]):
        evidence = make_return_evidence(accepted.space, accepted.actor)
        photos.append(evidence)
        asset = accepted.assets[index] if accepted.assets else None
        payload = return_data(accepted, evidence, asset)
        # Both the omitted and explicit-empty API representations are supported.
        if index:
            payload["box_code"] = ""
        response = accepted.client.post(return_url(loan), payload, format="json")
        assert response.status_code == 200, response.data
        assert response.data["assigned_box_id"] is None
        loan.refresh_from_db()
        item.refresh_from_db()
        assert loan.status == state
        assert loan.assigned_box_id is None
        assert item.returned_quantity == index + 1
        assert_stock(accepted.product, index + 1, 0, 1 - index)
        event = ReturnEvent.objects.get(request=loan, evidence=evidence)
        assert event.box_id is None
        assert event.actor_id == accepted.actor.pk
        assert event.remark == payload["remark"]
        if asset:
            link = item.asset_links.get(asset=asset)
            asset.refresh_from_db()
            assert asset.status == InventoryAsset.Status.AVAILABLE
            assert link.outcome == HardwareRequestItemAsset.Outcome.RETURNED
            assert link.return_event_id == event.pk
            assert link.returned_at is not None
            if not index:
                accepted.assets[1].refresh_from_db()
                assert accepted.assets[1].status == InventoryAsset.Status.ISSUED

    assert ReturnEvent.objects.filter(request=loan).count() == 2
    assert not BoxScan.objects.filter(request=loan).exists()
    logs = AuditLog.objects.filter(makerspace=accepted.space)
    assert not logs.filter(action="box.scanned").exists()
    for action, evidence in zip(["request.issued", "request.partially_returned", "request.returned"], photos):
        entry = logs.get(action=action, target_id=str(loan.pk))
        assert entry.actor_id == accepted.actor.pk
        assert entry.meta["box_id"] is None
        assert entry.meta["evidence_id"] == evidence.pk
        assert logs.filter(action="evidence.attached", target_id=str(evidence.pk), meta__request_id=loan.pk).exists()
        assert EvidenceUploadFinalization.objects.filter(evidence=evidence, status="finalized").exists()
    if accepted.assets:
        assert set(logs.filter(action="asset.issued", meta__request_id=loan.pk).values_list("target_id", flat=True)) == {
            str(asset.pk) for asset in accepted.assets
        }
        assert QrScanEvent.objects.filter(request=loan, context="return").count() == 2
    else:
        assert not HardwareRequestItemAsset.objects.filter(request_item=item).exists()
        assert not QrScanEvent.objects.filter(request=loan).exists()


@pytest.mark.parametrize("uploaded", [None, False])
def test_containerless_issue_still_requires_uploaded_evidence(accepted, uploaded):
    payload = {}
    if uploaded is False:
        payload = issue_payload(make_issue_evidence(accepted.space, accepted.actor))
        accepted.exists.return_value = False
    before = domain_snapshot(accepted)
    response = accepted.client.post(issue_url(accepted.loan), payload, format="json")
    assert response.status_code == (400 if uploaded is None else 409)
    if uploaded is False:
        assert response.data["code"] == "evidence_not_uploaded"
    assert domain_snapshot(accepted) == before


@pytest.mark.parametrize("accepted", [TrackingMode.INDIVIDUAL], indirect=True)
def test_containerless_individual_issue_still_requires_scans(accepted):
    evidence = make_issue_evidence(accepted.space, accepted.actor)
    before = domain_snapshot(accepted)
    response = accepted.client.post(issue_url(accepted.loan), issue_payload(evidence), format="json")
    assert response.status_code == 400
    assert "scanned asset QR" in response.data["detail"]
    assert domain_snapshot(accepted) == before


@pytest.mark.parametrize("invalid", ["no_evidence", "not_uploaded", "blank_remark", "unexpected_box"])
def test_containerless_return_rejection_does_not_mutate_loan(accepted, invalid):
    issue(accepted)
    evidence = make_return_evidence(accepted.space, accepted.actor)
    payload = return_data(accepted, evidence)
    if invalid == "no_evidence":
        del payload["evidence_id"]
    elif invalid == "not_uploaded":
        accepted.exists.return_value = False
    elif invalid == "blank_remark":
        payload["remark"] = "   "
    else:
        payload["box_code"] = make_box(accepted.space).code
    before = domain_snapshot(accepted)
    response = accepted.client.post(return_url(accepted.loan), payload, format="json")
    assert response.status_code == (409 if invalid == "not_uploaded" else 400)
    assert domain_snapshot(accepted) == before


@pytest.mark.parametrize("code", [None, "", "foreign"])
def test_assigned_container_return_requires_matching_code(accepted, code):
    box = make_box(accepted.space)
    assigned = accepted.client.post(assign_box_url(accepted.loan), {"box_code": box.code}, format="json")
    assert assigned.status_code == 200
    # This loan is intentionally container-backed; don't use the containerless issue helper.
    photo = make_issue_evidence(accepted.space, accepted.actor)
    issued = accepted.client.post(issue_url(accepted.loan), issue_payload(photo), format="json")
    assert issued.status_code == 200
    evidence = make_return_evidence(accepted.space, accepted.actor)
    payload = return_data(accepted, evidence)
    if code is not None:
        payload["box_code"] = make_box(make_space("foreign-box")).code if code == "foreign" else code
    before = domain_snapshot(accepted)
    rejected = accepted.client.post(return_url(accepted.loan), payload, format="json")
    assert rejected.status_code == 400
    assert rejected.data["code"] == "return_validation_error"
    assert domain_snapshot(accepted) == before
    payload["box_code"] = box.code
    payload["resolutions"][0]["returned"] = 2
    returned = accepted.client.post(return_url(accepted.loan), payload, format="json")
    assert returned.status_code == 200, returned.data
    assert returned.data["status"] == HardwareRequest.Status.RETURNED
    assert ReturnEvent.objects.get(request=accepted.loan).box_id == box.pk
    assert BoxScan.objects.filter(request=accepted.loan, box=box, context="return").count() == 1
    assert_stock(accepted.product, 2, 0, 0)


@pytest.mark.parametrize("actor_kind, status", [("machine_manager", 403), ("other_space", 404)])
def test_containerless_issue_and_return_enforce_authority(accepted, actor_kind, status):
    if actor_kind == "machine_manager":
        actor = make_print_manager("machine-manager", accepted.space)
    else:
        actor = make_handout_member("foreign-handover", make_space("other-space"))
    client = authenticated_client(actor)
    evidence = make_issue_evidence(accepted.space, accepted.actor)
    before = domain_snapshot(accepted)
    accepted.exists.reset_mock()
    denied = client.post(issue_url(accepted.loan), issue_payload(evidence), format="json")
    assert denied.status_code == status
    accepted.exists.assert_not_called()
    assert domain_snapshot(accepted) == before
    issue(accepted)
    evidence = make_return_evidence(accepted.space, accepted.actor)
    before = domain_snapshot(accepted)
    accepted.exists.reset_mock()
    denied = client.post(return_url(accepted.loan), return_data(accepted, evidence), format="json")
    assert denied.status_code == status
    accepted.exists.assert_not_called()
    assert domain_snapshot(accepted) == before
