"""Real HTTP/canonical movers and full persisted observations for print races."""
from types import SimpleNamespace

import pytest
from django.urls import reverse

from apps.audit import services as audit
from apps.audit.models import AuditLog, AuditMacKey
from apps.boxes.models import QrCode, QrScanEvent
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.operations.models import InventoryAdjustment, QrPrintBatch, QrPrintBatchItem
from apps.tenant_migration.models import SourceMigrationGate
from tests.box_parent_safety.pg_helpers import assert_maker_mode, maker_lock
from tests.qr_target_safety_helpers import (
    configure, jwt_client, qr_for, snapshot, space, staff, superadmin, target,
)


@pytest.fixture
def lab(settings):
    configure(settings)
    home, other = space(), space()
    actor, mover = staff(home, "inventory_manager"), superadmin()
    for tenant in (home, other):
        tenant.enabled_modules = sorted(set(tenant.enabled_modules) | {"asset_units", "qr_print_batches"})
        tenant.save(update_fields=["enabled_modules"])
        require_module(tenant, "qr_management")
        require_module(tenant, "asset_units")
        require_module(tenant, "qr_print_batches")
        # Initialize optional audit MAC keys before snapshots and concurrent work.
        audit.record(mover, "test.print_qr_fixture", makerspace=tenant, target=tenant)
    return SimpleNamespace(
        home=home, other=other, actor=actor, mover=mover,
        api=jwt_client(actor), move_api=jwt_client(mover),
        batch=QrPrintBatch.objects.create(makerspace=home, title="Race labels", created_by=actor),
    )


def prepare(lab, kind):
    obj = target(lab.home, kind)
    destination = InventoryProduct.objects.create(
        makerspace=lab.other, name="Destination drill",
        tracking_mode="individual" if kind == "asset" else "quantity",
        total_quantity=0, available_quantity=0,
    )
    return SimpleNamespace(
        kind=kind, obj=obj, destination=destination,
        qr=qr_for(lab.home, obj, kind, created_by=lab.mover),
        label=f"{obj.product.name} - {obj.asset_tag}" if kind == "asset" else obj.name,
    )


def add_http(lab, case, **data):
    return lab.api.post(
        reverse("qr-print-batch-items", args=[lab.batch.pk]),
        {"qr_code_id": case.qr.pk, **data}, format="json",
    )


def move_http(lab, case):
    data = {"target_type": case.kind, "target_id": case.destination.pk}
    if case.kind == "asset":
        data.update(target_id=case.obj.pk, destination_makerspace_id=lab.other.pk,
                    destination_product_id=case.destination.pk, new_name="Moved drill")
    return lab.move_api.post(
        reverse("qr-rebind-target", args=[case.qr.pk]), data, format="json",
    )


def frozen(value):
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, dict):
        return {key: frozen(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [frozen(item) for item in value]
    return value


def state():
    return frozen(snapshot(
        Makerspace, QrPrintBatch, InventoryAdjustment, SourceMigrationGate, AuditMacKey,
    ))


def row(model, pk):
    return frozen(model.objects.values().get(pk=pk))


def events():
    return AuditLog.objects.filter(action__startswith="qr_print_batch_item.").order_by("pk")


def assert_event(event, lab, item, action):
    assert (event.actor_id, event.makerspace_id, event.action, event.target_type,
            event.target_id, event.meta) == (
        lab.actor.pk, lab.home.pk, action, "operations.qrprintbatchitem", str(item.pk), {},
    )
    assert event.event_uuid is not None


def assert_item(lab, case, response):
    assert response.status_code == 201, response.data
    item = QrPrintBatchItem.objects.get(pk=response.data["id"])
    assert (item.batch_id, item.qr_code_id, item.target_type, item.target_id,
            item.label_text, item.sort_order) == (
        lab.batch.pk, case.qr.pk, case.kind, case.obj.pk, case.label, 0,
    )
    assert_event(events().get(), lab, item, "qr_print_batch_item.created")
    return item


def assert_moved(lab, case, response):
    assert response.status_code == 200, response.data
    qr = QrCode.objects.get(pk=case.qr.pk)
    assert (qr.makerspace_id, qr.target_type, qr.target_id, qr.status) == (
        lab.other.pk, case.kind,
        case.obj.pk if case.kind == "asset" else case.destination.pk, "active",
    )
    if case.kind == "asset":
        asset = InventoryAsset.objects.get(pk=case.obj.pk)
        assert (asset.makerspace_id, asset.product_id, asset.asset_tag) == (
            lab.other.pk, case.destination.pk, "Moved drill",
        )
    scan = QrScanEvent.objects.get(qr_code=qr, context="reassignment")
    assert (scan.makerspace_id, scan.actor_id) == (lab.other.pk, lab.mover.pk)
    action = "inventory.asset_moved_makerspace" if case.kind == "asset" else "qr.rebound"
    event = AuditLog.objects.get(action=action)
    assert (event.actor_id, event.makerspace_id) == (lab.mover.pk, lab.other.pk)


def qr_lock(statement):
    return 'FROM "boxes_qrcode"' in statement.sql and "FOR UPDATE" in statement.sql


def item_write(statement):
    return statement.sql.startswith((
        'INSERT INTO "operations_qrprintbatchitem"',
        'UPDATE "operations_qrprintbatchitem"',
        'DELETE FROM "operations_qrprintbatchitem"',
    ))


def audit_insert(statement):
    return statement.sql.startswith('INSERT INTO "audit_auditlog"')


def assert_no_writes(statements):
    tables = ("operations_qrprintbatchitem", "audit_auditlog", "boxes_qrcode",
              "boxes_qrscanevent", "inventory_inventoryasset", "inventory_inventoryproduct")
    assert not [s for s in statements if s.sql.startswith(("INSERT ", "UPDATE ", "DELETE "))
                and any(f'"{table}"' in s.sql for table in tables)]


def assert_qr_scope(statement, lab, case):
    for column, expected in (("id", case.qr.pk), ("makerspace_id", lab.home.pk)):
        predicate = f'"boxes_qrcode"."{column}" = %s'
        offset = statement.sql.index(predicate)
        assert statement.params[statement.sql[:offset].count("%s")] == expected, statement


def assert_order(worker, lab, case, *, wrote):
    statements = worker.statements
    makers = [(i, s) for i, s in enumerate(statements) if maker_lock(s)]
    assert len(makers) == 1, statements
    maker_index, maker = makers[0]
    assert_maker_mode(maker, "FOR NO KEY UPDATE")
    locks = [(i, s) for i, s in enumerate(statements) if qr_lock(s)]
    assert len(locks) == 1, statements
    qr_index, locked = locks[0]
    assert maker_index < qr_index and maker.completed and locked.completed
    assert locked.sql.rstrip().endswith("FOR UPDATE"), locked
    assert_qr_scope(locked, lab, case)
    # An unlocked A QR was cached before either tested wait; lock later rechecks A.
    cached = [s for s in statements[:maker_index]
              if 'FROM "boxes_qrcode"' in s.sql and "FOR " not in s.sql
              and case.qr.pk in s.params and s.completed]
    assert cached
    assert_qr_scope(cached[-1], lab, case)
    assert not any(s.sql.startswith('UPDATE "makerspaces_makerspace"') for s in statements)
    writes = [i for i, s in enumerate(statements) if item_write(s)]
    if wrote:
        assert writes and qr_index < min(writes)
        assert max(writes) < next(i for i, s in enumerate(statements) if audit_insert(s))
    else:
        assert_no_writes(statements)


def evidence(record_property, pending, blocker):
    record_property("postgres_wait_edge", repr({
        "waiter_pid": pending.pid, "blocker_pid": blocker,
        "full_sql": pending.sql, "params": pending.params,
        "observed_by": "pg_blocking_pids(waiter_pid)",
    }))


def record_protocol(record_property, worker):
    record_property("item_lock_and_write_sql", repr([
        {"pid": s.pid, "full_sql": s.sql, "params": s.params, "completed": s.completed}
        for s in worker.statements
        if maker_lock(s) or qr_lock(s) or item_write(s) or audit_insert(s)
    ]))
