"""F2 transfer status whitelist / loan guard, F3 container PATCH tenancy + typed errors."""
import pytest
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.boxes.models import Box
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.inventory.models import InventoryAsset, TrackingMode
from apps.operations.services_transfers import apply_stock_transfer
from tests.return_helpers import (
    authenticated_client,
    make_box,
    make_member,
    make_product,
    make_space,
    make_user,
)

pytestmark = pytest.mark.django_db


def _individual(slug, status=InventoryAsset.Status.AVAILABLE):
    makerspace = make_space(slug)
    manager = make_member(f"{slug}-sm", makerspace)
    issued = status == InventoryAsset.Status.ISSUED
    product = make_product(
        makerspace,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=0 if issued else 1,
        issued_quantity=1 if issued else 0,
    )
    asset = InventoryAsset.objects.create(
        makerspace=makerspace, product=product, asset_tag=f"{slug}-1", status=status
    )
    return makerspace, manager, product, asset


def _transfer(actor, makerspace, asset, to_status=""):
    return apply_stock_transfer(
        actor,
        makerspace,
        {"reason": "Move", "lines": [{"asset_id": asset.id, "to_status": to_status}]},
    )


@pytest.mark.parametrize("to_status", [InventoryAsset.Status.ISSUED, InventoryAsset.Status.RESERVED, InventoryAsset.Status.LOST])
def test_transfer_refuses_workflow_owned_target_status(to_status):
    makerspace, manager, product, asset = _individual(f"xfer-target-{to_status}")

    with pytest.raises(ValidationError) as exc:
        _transfer(manager, makerspace, asset, to_status)

    assert "to_status" in exc.value.detail
    asset.refresh_from_db()
    product.refresh_from_db()
    assert asset.status == InventoryAsset.Status.AVAILABLE
    assert (product.available_quantity, product.issued_quantity) == (1, 0)


def test_transfer_refuses_an_issued_asset():
    makerspace, manager, product, asset = _individual("xfer-issued", InventoryAsset.Status.ISSUED)

    with pytest.raises(ValidationError):
        _transfer(manager, makerspace, asset, InventoryAsset.Status.AVAILABLE)

    asset.refresh_from_db()
    product.refresh_from_db()
    assert asset.status == InventoryAsset.Status.ISSUED
    assert (product.available_quantity, product.issued_quantity) == (0, 1)


def test_transfer_refuses_an_asset_on_an_open_loan():
    makerspace, manager, _product, asset = _individual("xfer-loan")
    requester = make_user("xfer-loan-requester")
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ISSUED,
    )
    PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=request,
        requester=requester,
        target_type="asset",
        target_id=asset.id,
        target_label=asset.asset_tag,
        asset_ids=[asset.id],
    )

    with pytest.raises(ValidationError) as exc:
        _transfer(manager, makerspace, asset, InventoryAsset.Status.MAINTENANCE)

    assert "asset_id" in exc.value.detail


def test_transfer_still_shelves_an_available_asset():
    makerspace, manager, product, asset = _individual("xfer-ok")

    _transfer(manager, makerspace, asset, InventoryAsset.Status.MAINTENANCE)

    asset.refresh_from_db()
    product.refresh_from_db()
    assert asset.status == InventoryAsset.Status.MAINTENANCE
    assert (product.available_quantity, product.needs_fix_quantity) == (0, 1)


def _patch_container(user, box, data):
    return authenticated_client(user).patch(f"/api/v1/admin/containers/{box.id}", data, format="json")


def test_container_patch_cannot_move_container_to_another_makerspace():
    makerspace = make_space("box-tenant")
    other = make_space("box-tenant-other")
    manager = make_member("box-tenant-sm", makerspace)
    box = make_box(makerspace)

    response = _patch_container(manager, box, {"makerspace": other.id, "label": "Bin A"})

    assert response.status_code == 200
    box.refresh_from_db()
    assert (box.makerspace_id, box.label) == (makerspace.id, "Bin A")
    log = AuditLog.objects.get(action="container.updated", target_id=str(box.id))
    assert log.meta["fields"] == ["label"]


def test_container_patch_refuses_a_foreign_parent():
    makerspace = make_space("box-parent")
    other = make_space("box-parent-other")
    manager = make_member("box-parent-sm", makerspace)
    box = make_box(makerspace)

    response = _patch_container(manager, box, {"parent": make_box(other).id})

    assert response.status_code == 400
    assert "parent" in response.data
    box.refresh_from_db()
    assert box.parent_id is None


def test_container_parent_cycle_is_a_typed_400_on_patch_and_move():
    makerspace = make_space("box-cycle")
    manager = make_member("box-cycle-sm", makerspace)
    parent = make_box(makerspace)
    child = Box.objects.create(makerspace=makerspace, label="child", parent=parent)

    patch = _patch_container(manager, parent, {"parent": child.id})
    move = authenticated_client(manager).post(
        f"/api/v1/admin/containers/{parent.id}/move", {"parent_id": child.id}, format="json"
    )

    assert patch.status_code == 400
    assert "parent" in patch.data
    assert move.status_code == 400
    parent.refresh_from_db()
    assert parent.parent_id is None
