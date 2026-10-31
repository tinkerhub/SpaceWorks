"""Canonical QR asset transfers vs warranty writers, with real FK/host waits."""
import pytest
from django.db import connection, transaction

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import QrCode, QrScanEvent
from apps.operations.models import InventoryAdjustment
from apps.warranty.models import Warranty
from tests.document_safety.helpers import (
    accepted_body, finalize, jwt_client, lab, presign, usage,
)
from tests.document_safety.pg_helpers import (
    assert_maker_key_share_compatible, assert_no_maker_upgrade, race, statement,
)
from tests.document_safety.test_warranty import host_url

pytestmark = pytest.mark.django_db(transaction=True)


def transfer(case):
    root = User.objects.create_user(
        username="transfer-root", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    case.transfer_actor = root
    host = case.target.asset
    qr = QrCode.objects.create(
        makerspace=case.home, target_type=QrCode.TargetType.ASSET,
        target_id=host.pk, created_by=root,
    )
    product = host.product
    assert product.tracking_mode == "individual"
    assert (product.total_quantity, product.available_quantity) == (1, 1)

    def move():
        # Actual canonical changes run with actual FK checks at each statement.
        # This exposes their KEY SHARE locks before the test's SQL checkpoint.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            response = jwt_client(root).post(f"/api/v1/admin/qr/{qr.pk}/rebind-target", {
                "target_type": "asset", "target_id": host.pk,
                "destination_makerspace_id": case.other.pk, "new_name": "",
            }, format="json")
        return response
    return host, qr, product, move


def assert_transferred(case, host, qr, product):
    host.refresh_from_db()
    qr.refresh_from_db()
    product.refresh_from_db()
    assert host.makerspace_id == qr.makerspace_id == case.other.pk
    assert (product.total_quantity, product.available_quantity) == (0, 0)
    assert (host.product.total_quantity, host.product.available_quantity) == (1, 1)
    assert InventoryAdjustment.objects.filter(product__in=[product, host.product]).count() == 2
    assert QrScanEvent.objects.filter(qr_code=qr, context=QrScanEvent.Context.REASSIGNMENT).count() == 1
    assert AuditLog.objects.filter(action="inventory.asset_moved_makerspace").count() == 1


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("move_first", [False, True])
def test_canonical_asset_move_vs_upsert_waits_on_host_and_fresh_tenant_404(
    existing, move_first, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, "asset")
    host, qr, product, move = transfer(case)
    url = host_url(case)
    if not existing:
        case.target.delete()

    def put():
        # Global authority could resolve the moved asset; the original-tenant
        # predicate on the fresh host lock must still turn the stale request into 404.
        return jwt_client(case.transfer_actor).put(url, {"vendor_name": "Saved before transfer"}, format="json")

    if move_first:
        first, second, captured, _, _ = race(
            move, put,
            pause_after=lambda sql: sql.startswith('INSERT INTO "operations_inventoryadjustment"'),
            table="inventory_inventoryasset", clause="FOR UPDATE",
            before_release=assert_maker_key_share_compatible,
        )
        assert first.status_code == 200 and second.status_code == 404, (first.data, second.data)
        assert Warranty.objects.filter(asset=host).count() == int(existing)
        assert not AuditLog.objects.filter(action__in=["warranty.created", "warranty.updated"]).exists()
        assert_no_maker_upgrade(captured, "second")
    else:
        first, second, captured, _, _ = race(
            put, move, pause_after=statement("inventory_inventoryasset", "FOR UPDATE"),
            table="inventory_inventoryasset", clause="FOR UPDATE",
        )
        assert first.status_code == second.status_code == 200, (first.data, second.data)
        assert_no_maker_upgrade(captured, "first")
        assert Warranty.objects.get(asset=host).vendor_name == "Saved before transfer"
        assert AuditLog.objects.filter(action="warranty.updated" if existing else "warranty.created").count() == 1
    assert_transferred(case, host, qr, product)
    if Warranty.objects.filter(asset=host).exists():
        warranty = Warranty.objects.get(asset=host)
        assert warranty.makerspace_id == case.other.pk
        warranty.full_clean()


@pytest.mark.parametrize("move_first", [False, True])
@pytest.mark.parametrize("global_writer", [False, True])
def test_canonical_asset_move_vs_document_waits_on_warranty_without_maker_lock_upgrade(
    move_first, global_writer, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, "asset")
    host, qr, product, move = transfer(case)
    key, _ = presign(case)
    body = accepted_body("application/pdf")
    case.store.seed(case.module.staging_key(key), body)

    def attach():
        # Separate authenticated client per worker; no shared request/session state.
        client = jwt_client(case.transfer_actor if global_writer else case.actor)
        return client.post(case.url, {"object_key": key, "original_filename": "bill.pdf"}, format="json")

    if move_first:
        first, second, captured, _, _ = race(
            move, attach,
            pause_after=lambda sql: sql.startswith('INSERT INTO "operations_inventoryadjustment"'),
            table="warranty_warranty", clause="FOR UPDATE",
            before_release=assert_maker_key_share_compatible,
        )
        # A source-only actor loses scope (404); global authority reaches the fresh
        # tenant, where the retained source storage guard refuses it (typed 503).
        assert first.status_code == 200
        assert second.status_code == (503 if global_writer else 404), second.data
        if global_writer:
            assert second.data["code"] == "evidence_storage_unavailable"
        assert not case.model.objects.filter(object_key=key).exists()
        assert usage(case) == 0
        assert not AuditLog.objects.filter(action="warranty.document_added").exists()
        assert_no_maker_upgrade(captured, "second")
    else:
        first, second, captured, _, _ = race(
            attach, move, pause_after=statement("warranty_warranty", "FOR UPDATE"),
            table="warranty_warranty", clause="UPDATE",
        )
        assert (first.status_code, second.status_code) == (201, 200), (first.data, second.data)
        assert_no_maker_upgrade(captured, "first")
        locks = [sql for sql, _ in captured["first"]
                 if statement("makerspaces_makerspace", "FOR NO KEY UPDATE")(sql)]
        assert len(locks) >= 2, locks  # Both module lock AND finite add_storage lock.
        document = case.model.objects.get(object_key=key)
        assert document.warranty_id == case.target.pk and document.size_bytes == len(body)
        assert usage(case) == len(body)
        assert AuditLog.objects.filter(action="warranty.document_added").count() == 1
    assert case.store.objects[key][0] == body
    assert_transferred(case, host, qr, product)
    case.target.refresh_from_db()
    assert case.target.makerspace_id == case.other.pk
    case.target.full_clean()
