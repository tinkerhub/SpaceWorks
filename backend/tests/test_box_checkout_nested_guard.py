"""BOX-S01: descendants block implicit handover; empty descendants add no stock."""
import pytest

from apps.audit.models import AuditLog
from apps.boxes.models import QrScanEvent
from apps.hardware_requests.models import PublicToolLoan
from apps.inventory.models import InventoryAsset, InventoryProduct
from tests.atomic_publication.store import png
from tests.box_checkout_guard_helpers import (
    assert_png_promoted, assert_refusal, assert_scanner_refusal, box_qr,
    checkout, checkout_lab, contained_unit, resolve_actions, root_kit,
    snapshot, uploaded_photo,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("transport", ["post", "put"])
@pytest.mark.parametrize("surface", ["public", "direct"])
@pytest.mark.parametrize("descendant", [
    "child-unit", "grandchild-unit", "hidden-child-unit", "disabled-grandchild-unit",
    "inactive-grandchild-unit", "child-quantity", "grandchild-quantity",
    "hidden-child-quantity", "disabled-grandchild-quantity", "inactive-child-quantity",
])
def test_nested_stock_refuses_box_checkout_and_scanner(
    monkeypatch, settings, transport, surface, descendant,
):
    lab = checkout_lab(monkeypatch, settings, transport)
    root, qr = root_kit(lab)
    child, _ = box_qr(lab, parent=root, label="Child compartment")
    grandchild, _ = box_qr(lab, parent=child, label="Grandchild compartment")
    target = grandchild if "grandchild" in descendant else child
    if descendant.endswith("unit"):
        unit = contained_unit(lab, target)
        product = unit.product
        if "disabled" in descendant:
            unit.asset.public_self_checkout_enabled = False
            unit.asset.save(update_fields=["public_self_checkout_enabled"])
        unit.asset.refresh_from_db()
        assert unit.asset.status == InventoryAsset.Status.AVAILABLE
    else:
        product = InventoryProduct.objects.create(
            makerspace=lab.space, name="PRIVATE nested spares", box=target,
            total_quantity=2, available_quantity=2,
            is_public=True, public_self_checkout_enabled=True,
        )
    if "hidden" in descendant:
        product.is_public = False
        product.save(update_fields=["is_public"])
    if "disabled" in descendant:
        product.public_self_checkout_enabled = False
        product.save(update_fields=["public_self_checkout_enabled"])
    if "inactive" in descendant:
        target.is_active = False
        target.save(update_fields=["is_active"])

    assert_refusal(lab, surface, qr)
    assert_scanner_refusal(lab, qr)


@pytest.mark.parametrize("transport", ["post", "put"])
@pytest.mark.parametrize("surface", ["public", "direct"])
def test_empty_descendants_keep_quantity_checkout_at_root_only(
    monkeypatch, settings, transport, surface,
):
    lab = checkout_lab(monkeypatch, settings, transport)
    root, qr = root_kit(lab)
    child, child_qr = box_qr(lab, parent=root, label="Empty child")
    grandchild, grandchild_qr = box_qr(lab, parent=child, label="Empty grandchild", active=False)
    empty_product = InventoryProduct.objects.create(
        makerspace=lab.space, name="Empty nested stock", box=grandchild,
        total_quantity=0, available_quantity=0,
    )
    extra_root = InventoryProduct.objects.create(
        makerspace=lab.space, name="Second root quantity kit", box=root,
        total_quantity=5, available_quantity=5, is_public=True, public_self_checkout_enabled=True,
    )
    actions = resolve_actions(lab, qr)
    assert {"view", "contents", "checkout", "direct_handout"} <= actions
    evidence = uploaded_photo(lab, surface)
    before = snapshot()
    response = checkout(lab, surface, [qr], evidence)
    assert response.status_code == 201, response.data
    assert sorted(response.data["items"], key=lambda row: row["product_name"]) == sorted([
        {"product_name": lab.product.name, "quantity": 1},
        {"product_name": extra_root.name, "quantity": 1},
    ], key=lambda row: row["product_name"])
    loan = PublicToolLoan.objects.get()
    actor = lab.borrower if surface == "public" else lab.actor
    assert (loan.container_id, loan.qr_code_id, loan.qr_ids, loan.asset_ids) == (
        root.pk, qr.pk, [qr.pk], [],
    )
    assert loan.request.issue_evidence_id == evidence.pk
    assert loan.request.status == "issued"
    items = list(loan.request.items.values_list(
        "product_id", "requested_quantity", "accepted_quantity", "issued_quantity",
    ))
    assert set(items) == {(lab.product.pk, 1, 1, 1), (extra_root.pk, 1, 1, 1)}
    assert len(items) == 2
    for product, total in [(lab.product, 3), (extra_root, 5), (empty_product, 0)]:
        product.refresh_from_db()
        issued = int(product.pk != empty_product.pk)
        assert (product.total_quantity, product.available_quantity, product.issued_quantity) == (
            total, total - issued, issued,
        )
    assert not InventoryAsset.objects.filter(makerspace=lab.space).exists()
    scans = QrScanEvent.objects.filter(request=loan.request)
    assert list(scans.values_list("qr_code_id", "actor_id", "context")) == [(qr.pk, actor.pk, "issue")]
    assert not scans.filter(qr_code__in=[child_qr, grandchild_qr]).exists()
    after = snapshot()
    previous_scan_ids = {row["id"] for row in before["QrScanEvent"]}
    new_scans = [row for row in after["QrScanEvent"] if row["id"] not in previous_scan_ids]
    assert [(row["qr_code_id"], row["actor_id"], row["request_id"], row["context"])
            for row in new_scans] == [(qr.pk, actor.pk, loan.request_id, "issue")]
    assert after["BoxScan"] == before["BoxScan"]
    assert_png_promoted(lab, evidence, charged=transport == "put")
    lab.space.refresh_from_db()
    assert lab.space.storage_bytes_used == (len(png()) if transport == "put" else 0)
    action = "public_tool.checked_out" if surface == "public" else "admin_direct.checked_out"
    entries = AuditLog.objects.filter(makerspace=lab.space, action=action)
    assert set(entries.values_list("actor_id", flat=True)) == {actor.pk}
    assert entries.count() == (1 if surface == "public" else 2)
    assert len(snapshot()["HardwareRequest"]) == len(before["HardwareRequest"]) + 1
    # Occupied boxes still allow reading contents while suppressing fresh issue actions.
    assert_scanner_refusal(lab, qr)


@pytest.mark.parametrize("contents", ["unit", "quantity"])
def test_container_only_handout_still_refuses_descendant_stock(monkeypatch, settings, contents):
    lab = checkout_lab(monkeypatch, settings, "put")
    root, _ = box_qr(lab)
    child, _ = box_qr(lab, parent=root, label="Nested contents")
    if contents == "unit":
        contained_unit(lab, child)
    else:
        InventoryProduct.objects.create(
            makerspace=lab.space, name="Nested quantity", box=child,
            total_quantity=2, available_quantity=2,
        )
    evidence = uploaded_photo(lab, "direct")
    before = snapshot()
    response = checkout(lab, "direct", [], evidence, container=root)
    assert response.status_code == 400, response.data
    assert str(response.data["detail"]).startswith("Container is not empty.")
    assert snapshot() == before
    assert_png_promoted(lab, evidence)
