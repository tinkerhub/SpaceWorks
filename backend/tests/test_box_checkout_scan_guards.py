"""HW002 functional refusal, scanner parity and explicit unit handover lifecycles."""
import pytest

from apps.audit.models import AuditLog
from apps.boxes.models import QrScanEvent
from apps.boxes.services import revoke_qr_code
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan, ReturnEvent
from apps.inventory.models import InventoryAsset, InventoryProduct
from tests.atomic_publication.store import png
from tests.box_checkout_guard_helpers import (
    assert_png_promoted, assert_refusal, assert_scanner_refusal, box_qr,
    checkout, checkout_lab, contained_unit, root_kit, snapshot, uploaded_photo,
)
from tests.inventory_lending_helpers import submit_request

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("transport", ["post", "put"])
@pytest.mark.parametrize("surface", ["public", "direct"])
@pytest.mark.parametrize("unit_case", [
    "available", "hidden", "checkout-disabled", "archived-product",
    "zero-aggregate-legacy", "no-active-qr",
])
def test_box_qr_refuses_available_unit_without_mutation(
    monkeypatch, settings, transport, surface, unit_case,
):
    lab = checkout_lab(monkeypatch, settings, transport)
    box, qr = root_kit(lab)
    unit = contained_unit(lab, box)
    if unit_case == "hidden":
        unit.product.is_public = False
        unit.product.save(update_fields=["is_public"])
    elif unit_case == "checkout-disabled":
        unit.asset.public_self_checkout_enabled = False
        unit.asset.save(update_fields=["public_self_checkout_enabled"])
    elif unit_case == "archived-product":
        unit.product.is_archived = True
        unit.product.save(update_fields=["is_archived"])
    elif unit_case == "zero-aggregate-legacy":
        # Deliberately corrupt only this historical aggregate; the physical unit
        # remains canonically generated and AVAILABLE, so it must still block.
        InventoryProduct.objects.filter(pk=unit.product.pk).update(available_quantity=0)
    elif unit_case == "no-active-qr":
        revoke_qr_code(lab.actor, unit.qr)

    assert_refusal(lab, surface, qr)
    assert_scanner_refusal(lab, qr)


@pytest.mark.parametrize("surface", ["public", "direct"])
@pytest.mark.parametrize("hold_state", ["issued", "partially_returned"])
def test_scanner_and_checkout_respect_real_reviewed_box_hold(
    monkeypatch, settings, surface, hold_state,
):
    lab = checkout_lab(monkeypatch, settings)
    box, qr = root_kit(lab)
    request = submit_request(lab, quantity=2)
    workflow.accept_request(lab.actor, request)
    request = workflow.assign_box(lab.actor, request, box.code)
    issue = uploaded_photo(lab, "direct")
    request = workflow.issue_request(lab.actor, request, issue.pk, remark="Reviewed kit issued")
    if hold_state == "partially_returned":
        evidence = uploaded_photo(lab, "direct", "return")
        response = lab.client.post(
            f"/api/v1/admin/requests/{request.pk}/return",
            {"evidence_id": evidence.pk, "box_code": box.code, "remark": "One back",
             "resolutions": [{"item_id": request.items.get().pk, "returned": 1}]},
            format="json",
        )
        assert response.status_code == 200, response.data
    request.refresh_from_db()
    assert request.status == hold_state
    assert not PublicToolLoan.objects.exists()
    assert_refusal(lab, surface, qr, detail="This box is already checked out.")
    assert_scanner_refusal(lab, qr)


@pytest.mark.parametrize("transport", ["post", "put"])
@pytest.mark.parametrize("surface", ["public", "direct"])
def test_explicit_asset_qrs_issue_and_return_exact_units(
    monkeypatch, settings, transport, surface,
):
    lab = checkout_lab(monkeypatch, settings, transport, individual=True)
    container = None
    box_code = None
    # Standalone public unit vs staff-selected container with EACH unit scanned.
    count = 1 if surface == "public" else 3
    if surface == "direct":
        container, box_code = box_qr(lab)
        lab.product.box = container
        lab.product.save(update_fields=["box"])
        for asset in lab.assets:
            asset.box = container
            asset.save(update_fields=["box"])
    qrs = lab.qrs[:count]
    assets = lab.assets[:count]
    evidence = uploaded_photo(lab, surface)
    response = checkout(lab, surface, qrs, evidence, container=container)
    assert response.status_code == 201, response.data
    loan = PublicToolLoan.objects.get()
    actor = lab.borrower if surface == "public" else lab.actor
    assert loan.container_id == (container.pk if container else None)
    assert loan.qr_ids == [qr.pk for qr in qrs]
    assert loan.asset_ids == [asset.pk for asset in assets]
    assert loan.source == ("public_self_checkout" if surface == "public" else "admin_direct")
    assert loan.request.issue_evidence_id == evidence.pk
    assert loan.request.requester_id == lab.borrower.pk
    assert loan.request.issued_by_id == actor.pk
    assert loan.request.status == HardwareRequest.Status.ISSUED
    assert loan.due_at == loan.request.return_due_at
    item = loan.request.items.get()
    assert (item.product_id, item.requested_quantity, item.accepted_quantity, item.issued_quantity) == (
        lab.product.pk, count, count, count,
    )
    lab.product.refresh_from_db()
    assert (lab.product.total_quantity, lab.product.available_quantity, lab.product.issued_quantity) == (
        3, 3 - count, count,
    )
    assert set(InventoryAsset.objects.filter(product=lab.product, status="issued").values_list(
        "pk", flat=True,
    )) == {asset.pk for asset in assets}
    scans = QrScanEvent.objects.filter(request=loan.request, context="issue")
    assert scans.count() == count
    assert set(scans.values_list("qr_code_id", "actor_id")) == {(qr.pk, actor.pk) for qr in qrs}
    if box_code:
        assert box_code.pk not in loan.qr_ids
        assert not QrScanEvent.objects.filter(request=loan.request, qr_code=box_code).exists()
    action = "public_tool.checked_out" if surface == "public" else "admin_direct.checked_out"
    entry = AuditLog.objects.get(makerspace=lab.space, action=action)
    assert entry.actor_id == actor.pk
    assert entry.target_id == str(loan.request_id if surface == "public" else lab.product.pk)
    if surface == "direct":
        assert entry.meta["loan_id"] == loan.pk and entry.meta["quantity"] == count
        attached = AuditLog.objects.get(makerspace=lab.space, action="evidence.attached")
        assert (attached.actor_id, attached.meta["evidence_id"]) == (actor.pk, evidence.pk)
    assert_png_promoted(lab, evidence, charged=transport == "put")
    lab.space.refresh_from_db()
    assert lab.space.storage_bytes_used == (len(png()) if transport == "put" else 0)
    assert evidence.object_key not in str(response.data)

    returned_photo = uploaded_photo(lab, surface, "return")
    notes = "Physically checked the identified units; all in good condition."
    if surface == "public":
        client = lab.public
        url = f"/api/v1/public/{lab.space.slug}/tools/return"
        body = {"evidence_id": returned_photo.pk, "payload": qrs[0].payload, "remark": notes}
        bad = {**body, "payload": lab.qrs[-1].payload}
        expected_error = 409
    else:
        client = lab.client
        url = f"/api/v1/admin/direct-loans/{loan.pk}/return"
        body = {
            "evidence_id": returned_photo.pk, "qr_payload": qrs[0].payload, "notes": notes,
            "resolutions": [{"item_id": item.pk, "returned": count, "assets": [
                {"asset_id": asset.pk, "outcome": "returned"} for asset in assets
            ]}],
        }
        bad = {**body, "qr_payload": box_code.payload}
        expected_error = 400
    before = snapshot()
    refused = client.post(url, bad, format="json")
    assert refused.status_code == expected_error, refused.data
    assert snapshot() == before
    if surface == "direct":
        # A selected container is no substitute for unit QR proof on return.
        missing_scan = client.post(url, {**body, "qr_payload": ""}, format="json")
        assert missing_scan.status_code == 400, missing_scan.data
        assert snapshot() == before
    returned = client.post(url, body, format="json")
    assert returned.status_code == 200, returned.data
    loan.refresh_from_db()
    loan.request.refresh_from_db()
    item.refresh_from_db()
    lab.product.refresh_from_db()
    assert (loan.status, loan.request.status, loan.return_evidence_id, loan.return_notes) == (
        "returned", "returned", returned_photo.pk, notes,
    )
    assert item.returned_quantity == count
    assert (lab.product.available_quantity, lab.product.reserved_quantity, lab.product.issued_quantity) == (3, 0, 0)
    assert (lab.product.total_quantity, lab.product.damaged_quantity,
            lab.product.lost_quantity, lab.product.needs_fix_quantity) == (3, 0, 0, 0)
    assert (item.damaged_quantity, item.missing_quantity, item.needs_fix_quantity) == (0, 0, 0)
    assert list(InventoryAsset.objects.filter(product=lab.product).values_list("status", flat=True)) == [
        InventoryAsset.Status.AVAILABLE,
    ] * 3
    return_scan = QrScanEvent.objects.get(request=loan.request, context="return")
    assert (return_scan.qr_code_id, return_scan.actor_id) == (qrs[0].pk, actor.pk)
    action = "public_tool.returned" if surface == "public" else "admin_direct.returned"
    assert AuditLog.objects.get(makerspace=lab.space, action=action).actor_id == actor.pk
    if surface == "direct":
        event = ReturnEvent.objects.get(request=loan.request)
        assert (event.evidence_id, event.box_id, event.actor_id, event.remark) == (
            returned_photo.pk, container.pk, actor.pk, notes,
        )
    assert_png_promoted(lab, returned_photo, charged=transport == "put")
    lab.space.refresh_from_db()
    assert lab.space.storage_bytes_used == (2 * len(png()) if transport == "put" else 0)


# BOX + contained ASSET overlap remains a separate 409 contract, covered unchanged
# by test_qr_checkout_target_overlap.py::test_box_and_contained_asset_qrs_are_rejected_before_issuance.
