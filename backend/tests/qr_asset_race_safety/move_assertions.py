"""Canonical move effects, including complete old rows and exact new history."""
from apps.audit.models import AuditLog
from apps.boxes.models import QrCode, QrScanEvent
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.operations.models import InventoryAdjustment
from apps.warranty.models import Warranty
from tests.qr_asset_race_safety.helpers import (
    assert_changed, assert_event, move_dto, new_rows, row, state,
)


def assert_moved(lab, qr, before, response):
    assert response.status_code == 200, response.data
    after = state()
    asset, warranty = row(InventoryAsset, lab.asset.pk), row(Warranty, lab.warranty.pk)
    qr.refresh_from_db()
    assert response.data == move_dto(qr)
    assert response.data["qr"]["makerspace"] == lab.other.pk
    old = lambda model, pk: next(r for r in before[model._meta.label_lower] if r["id"] == pk)
    assert_changed(old(InventoryAsset, lab.asset.pk), asset,
                   makerspace_id=lab.other.pk, product_id=lab.destination.pk,
                   box_id=None, public_self_checkout_enabled=False, asset_tag="Moved asset")
    assert_changed(old(QrCode, qr.pk), row(QrCode, qr.pk), makerspace_id=lab.other.pk)
    assert_changed(old(Warranty, lab.warranty.pk), warranty, makerspace_id=lab.other.pk)
    assert_changed(old(InventoryProduct, lab.product.pk), row(InventoryProduct, lab.product.pk),
                   total_quantity=0, available_quantity=0)
    assert_changed(old(InventoryProduct, lab.destination.pk), row(InventoryProduct, lab.destination.pk),
                   total_quantity=1, available_quantity=1)
    assert not QrCode.objects.filter(makerspace=lab.home, target_type="asset",
                                     target_id=lab.asset.pk).exists()
    assert QrCode.objects.filter(target_type="asset", target_id=lab.asset.pk,
                                 status="active").count() == 1
    assert not lab.home.warranties.exists()
    assert list(lab.other.warranties.values_list("pk", flat=True)) == [lab.warranty.pk]
    lab.warranty.refresh_from_db()
    lab.warranty.full_clean()

    scans = new_rows(before, after, QrScanEvent)
    assert len(scans) == 1
    scan = scans[0]
    assert scan == {
        "id": scan["id"], "makerspace_id": lab.other.pk, "qr_code_id": qr.pk,
        "actor_id": lab.mover.pk, "context": "reassignment", "request_id": None,
        "created_at": scan["created_at"],
    }
    adjustments = new_rows(before, after, InventoryAdjustment)
    assert len(adjustments) == 2
    events = new_rows(before, after, AuditLog)
    assert len(events) == 3
    for product, tenant, delta, direction in (
        (lab.product, lab.home, -1, "out"), (lab.destination, lab.other, 1, "in"),
    ):
        reason = f"Cross-makerspace asset move ({direction})"
        adjustment = next(r for r in adjustments if r["product_id"] == product.pk)
        assert adjustment == {
            "id": adjustment["id"], "makerspace_id": tenant.pk, "product_id": product.pk,
            "stocktake_id": None, "transfer_id": None, "asset_id": None,
            "delta_available": delta, "delta_damaged": 0, "delta_lost": 0,
            "reason": reason, "created_by_id": lab.mover.pk,
            "created_at": adjustment["created_at"],
        }
        event = next(r for r in events if r["action"] == "inventory.quantity_adjusted"
                     and r["target_id"] == str(product.pk))
        assert_event(event, lab.mover, tenant, product, "inventory.quantity_adjusted", {
            "delta_available": delta, "delta_damaged": 0, "delta_lost": 0, "reason": reason,
        })
    moved = next(r for r in events if r["action"] == "inventory.asset_moved_makerspace")
    assert_event(moved, lab.mover, lab.other, lab.asset, "inventory.asset_moved_makerspace", {
        "old_makerspace_id": lab.home.pk, "new_makerspace_id": lab.other.pk,
        "asset_id": lab.asset.pk, "dest_product_id": lab.destination.pk,
        "old_tag": lab.asset.asset_tag, "new_tag": "Moved asset", "warranty_id": lab.warranty.pk,
    })
    # Reconstruct the entire snapshot: no discarded columns, counters, or history.
    expected = {**before}
    for model, pks in ((InventoryAsset, {lab.asset.pk}), (QrCode, {qr.pk}),
                       (Warranty, {lab.warranty.pk}),
                       (InventoryProduct, {lab.product.pk, lab.destination.pk})):
        key = model._meta.label_lower
        expected[key] = [row(model, r["id"]) if r["id"] in pks else r for r in before[key]]
    for model, added in ((QrScanEvent, scans), (InventoryAdjustment, adjustments), (AuditLog, events)):
        key = model._meta.label_lower
        expected[key] = sorted([*before[key], *added], key=lambda r: r["id"])
    assert after == expected
    assert not [event for event in events if event["action"] == "qr.created"]
    return after
