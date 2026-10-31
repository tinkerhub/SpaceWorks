"""Real staff HTTP, legal inventory and canonical moves for batch projection tests."""
from types import SimpleNamespace

from django.utils.dateparse import parse_datetime

from apps.accounts.models import User
from apps.boxes.models import QrCode, QrScanEvent
from apps.boxes.qr_admission import create_tool_qr
from apps.boxes.rebind import rebind_qr_target
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.makerspaces.module_install import install_module
from apps.makerspaces.roles import ensure_default_roles
from apps.operations.models import QrPrintBatch, QrPrintBatchItem
from tests.operations.qr_safety_helpers import (
    add_item, create_batch, generate, jwt_client, qr_lab, state,
)


def manager(username, spaces):
    actor = User.objects.create_user(username=username, role=User.Role.REQUESTER)
    for space in spaces:
        ensure_default_roles(space)
        role = MakerspaceRole.objects.get(makerspace=space, slug="inventory_manager")
        MakerspaceMembership.objects.create(
            user=actor, makerspace=space, role="inventory_manager", assigned_role=role,
        )
    return actor


def projection_lab(settings):
    lab = qr_lab(settings)
    lab.global_actor = User.objects.create_user(
        username="batch-projection-global", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE, is_staff=True, is_superuser=True,
    )
    for space in (lab.home, lab.other):
        for key in ("qr_management", "qr_print_batches", "asset_units"):
            install_module(space, key, actor=lab.global_actor)
    lab.b_actor = manager("batch-projection-b", [lab.other])
    lab.both_actor = manager("batch-projection-both", [lab.home, lab.other])
    lab.b_client = jwt_client(lab.b_actor)
    lab.both_client = jwt_client(lab.both_actor)
    lab.global_client = jwt_client(lab.global_actor)
    response = create_batch(lab, "Historical A batch")
    assert response.status_code == 201, response.data
    lab.batch = QrPrintBatch.objects.get(pk=response.data["id"])
    assert not lab.actor.makerspace_memberships.filter(makerspace=lab.other).exists()
    return lab


def target_product(space, name, *, individual=False):
    return InventoryProduct.objects.create(
        makerspace=space, name=name,
        tracking_mode=TrackingMode.INDIVIDUAL if individual else TrackingMode.QUANTITY,
        total_quantity=0 if individual else 1,
        available_quantity=0 if individual else 1,
    )


def collect(lab, *, kind="product", label="Original moved label", order=20):
    source = target_product(lab.home, label, individual=kind == "asset")
    if kind == "asset":
        response = generate(lab, source)
        assert response.status_code == 201, response.data
        unit = response.data["assets"][0]
        code = QrCode.objects.get(pk=unit["qr"]["id"])
        target = InventoryAsset.objects.get(pk=unit["id"])
    else:
        target = source
        code = create_tool_qr(lab.actor, lab.home.pk, target, QrCode.TargetType.PRODUCT)
    response = add_item(lab, lab.batch, code, label_text=label, sort_order=order)
    assert response.status_code == 201, response.data
    item = QrPrintBatchItem.objects.get(pk=response.data["id"])
    return SimpleNamespace(source=source, target=target, code=code, item=item)


def item_rows(batch):
    return list(batch.items.order_by("pk").values())


def move(lab, collected, kind):
    """TRANSFER_STOCK is platform-only: never forge it on a local custom role."""
    before = item_rows(lab.batch)
    original_id = collected.target.pk
    data = {"target_type": kind, "target_id": original_id, "new_name": "B private target"}
    destination = target_product(lab.other, "B replacement", individual=kind == "asset")
    if kind == "asset":
        data.update(destination_makerspace_id=lab.other.pk, destination_product_id=destination.pk)
    else:
        data["target_id"] = destination.pk
    result = rebind_qr_target(lab.global_actor, collected.code.pk, data)
    collected.code.refresh_from_db()
    collected.target.refresh_from_db()
    assert result.qr.pk == collected.code.pk
    assert collected.code.makerspace_id == lab.other.pk
    assert collected.code.target_id == (original_id if kind == "asset" else destination.pk)
    if kind == "asset":
        assert collected.target.makerspace_id == lab.other.pk
        assert collected.target.product_id == destination.pk
        collected.source.refresh_from_db()
        destination.refresh_from_db()
        assert (collected.source.available_quantity, destination.available_quantity) == (0, 1)
    assert item_rows(lab.batch) == before
    return destination


def read_state():
    snapshot = state()
    snapshot["boxes.QrScanEvent"] = list(QrScanEvent.objects.order_by("pk").values())
    return snapshot


def detail_url(lab):
    return f"/api/v1/admin/qr-print-batches/{lab.batch.pk}"


def snapshot_fields(item):
    return {name: getattr(item, name) for name in (
        "id", "label_text", "target_type", "target_id", "sort_order",
    )}


def expected_qr(code):
    # Independent contract oracle: don't ask the serializer under test for its answer.
    return {
        "id": code.pk, "makerspace": code.makerspace_id, "payload": code.payload,
        "target_type": code.target_type, "target_id": code.target_id,
        "status": code.status, "created_at": code.created_at,
        "updated_at": code.updated_at, "revoked_at": code.revoked_at,
    }


def assert_qr(actual, code):
    actual = dict(actual)
    for field in ("created_at", "updated_at", "revoked_at"):
        if actual[field] is not None:
            actual[field] = parse_datetime(actual[field])
    assert actual == expected_qr(code)
