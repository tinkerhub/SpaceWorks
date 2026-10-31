"""Stable HTTP fixtures and complete persisted observations, without lock substitutes."""
from types import SimpleNamespace

import pytest
from django.db import connection
from django.urls import reverse

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog, AuditMacKey
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.boxes.serializers import QrCodeSerializer, qr_target_payload
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.operations.models import InventoryAdjustment
from apps.tenant_migration.models import SourceMigrationGate
from apps.warranty.models import Warranty, WarrantyDocument
from tests.qr_target_safety_helpers import (
    configure, jwt_client, qr_for, snapshot, space, staff, superadmin, target,
)


@pytest.fixture
def lab(settings):
    configure(settings)
    home, other = space(), space()
    for tenant in (home, other):
        tenant.enabled_modules = sorted(set(tenant.enabled_modules) | {"asset_units"})
        tenant.save(update_fields=["enabled_modules"])
    actor, mover = staff(home), superadmin()
    asset = target(home, "asset")
    box = Box.objects.create(makerspace=home, label="Original asset container")
    asset.box, asset.public_self_checkout_enabled = box, True
    asset.save(update_fields=["box", "public_self_checkout_enabled"])
    destination = InventoryProduct.objects.create(
        makerspace=other, name="Destination tool", tracking_mode="individual",
        total_quantity=0, available_quantity=0,
    )
    warranty = Warranty.objects.create(makerspace=home, asset=asset, vendor_name="Acme")
    document = WarrantyDocument.objects.create(
        warranty=warranty, object_key=f"warranty/{home.pk}/receipt.pdf",
        original_filename="receipt.pdf", content_type="application/pdf", size_bytes=10,
    )
    # Initialize audit keys before a baseline; no QR-created event is fabricated.
    for tenant in (home, other):
        audit.record(mover, "test.asset_qr_fixture", makerspace=tenant, target=tenant)
    return SimpleNamespace(
        home=home, other=other, actor=actor, mover=mover, asset=asset,
        product=asset.product, destination=destination, warranty=warranty,
        document=document, api=jwt_client(actor), move_api=jwt_client(mover),
    )


def code(lab):
    qr = qr_for(lab.home, lab.asset, "asset", created_by=lab.mover)
    QrScanEvent.objects.create(
        makerspace=lab.home, qr_code=qr, actor=lab.actor, context="inventory_check",
    )
    return qr


def asset_http(lab, **headers):
    return lab.api.post(reverse("asset-qr", args=[lab.asset.pk]), {}, format="json", **headers)


def move_http(lab, qr):
    return lab.move_api.post(
        reverse("qr-rebind-target", args=[qr.pk]),
        {"target_type": "asset", "target_id": lab.asset.pk,
         "destination_makerspace_id": lab.other.pk,
         "destination_product_id": lab.destination.pk, "new_name": "Moved asset"},
        format="json",
    )


def frozen(value):
    """Keep every column, converting PostgreSQL binary views before copying."""
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, dict):
        return {key: frozen(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [frozen(item) for item in value]
    return value


def state():
    return frozen(snapshot(
        Makerspace, Warranty, WarrantyDocument, InventoryAdjustment,
        SourceMigrationGate, AuditMacKey, User, MakerspaceMembership, MakerspaceRole,
    ))


def row(model, pk):
    return frozen(model.objects.values().get(pk=pk))


def dto(qr):
    return dict(QrCodeSerializer(qr).data)


def move_dto(qr):
    return {"qr": dto(qr), "target": qr_target_payload(qr)}


def lock_on(table):
    return lambda statement: f'FROM "{table}"' in statement.sql and "FOR UPDATE" in statement.sql


qr_lock = lock_on("boxes_qrcode")
asset_lock = lock_on("inventory_inventoryasset")


def audit_insert(statement):
    return statement.sql.startswith('INSERT INTO "audit_auditlog"')


def source_shared(statement):
    return "pg_advisory_xact_lock_shared(" in statement.sql


def backend_pid():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]


def assert_no_domain_write(statements):
    tables = ("boxes_qrcode", "boxes_qrscanevent", "inventory_inventoryasset",
              "inventory_inventoryproduct", "audit_auditlog", "operations_inventoryadjustment")
    assert not [s for s in statements if s.sql.startswith(("UPDATE ", "INSERT ", "DELETE "))
                and any(f'"{table}"' in s.sql for table in tables)]


def record_sql(record_property, worker, label):
    record_property(label, repr([
        {"sql": s.sql, "params": s.params, "pid": s.pid, "completed": s.completed}
        for s in worker.statements
    ]))


def assert_lock_order(worker, *, existing=True):
    from tests.box_parent_safety.pg_helpers import assert_maker_mode, maker_lock

    locks = [(i, s) for i, s in enumerate(worker.statements) if maker_lock(s)]
    assert len(locks) == 1, worker.statements
    maker_index, maker = locks[0]
    assert_maker_mode(maker, "FOR NO KEY UPDATE")
    qr_index = next(i for i, s in enumerate(worker.statements) if qr_lock(s))
    asset_index = next(i for i, s in enumerate(worker.statements) if asset_lock(s))
    assert maker_index < qr_index < asset_index
    assert maker.completed and worker.statements[qr_index].completed
    assert worker.statements[asset_index].completed
    # No Maker UPDATE statement or later lock upgrade is hidden among other SQL.
    assert not [s for s in worker.statements if s.sql.startswith('UPDATE "makerspaces_makerspace"')]
    assert not [s for s in worker.statements if s.sql.startswith('UPDATE "boxes_qrcode"')]
    if existing:
        assert_no_domain_write(worker.statements)


def new_rows(before, after, model):
    key = model._meta.label_lower
    old = {item["id"]: item for item in before[key]}
    current = {item["id"]: item for item in after[key]}
    assert all(current[pk] == item for pk, item in old.items())
    return [item for pk, item in current.items() if pk not in old]


def assert_event(event, actor, tenant, target, action, meta):
    assert (event["actor_id"], event["makerspace_id"], event["target_type"],
            event["target_id"], event["action"], event["meta"]) == (
        actor.pk, tenant.pk, target._meta.label_lower, str(target.pk), action, meta,
    )
    assert event["event_uuid"] is not None
    assert event["row_mac"] is None or len(event["row_mac"]) == 32


def assert_changed(before, after, **changes):
    assert after["updated_at"] >= before["updated_at"]
    assert after == {**before, **changes, "updated_at": after["updated_at"]}


def assert_created(lab, before, response):
    assert response.status_code == 201, response.data
    qr = QrCode.objects.get(pk=response.data["id"])
    assert response.data == dto(qr)
    after = state()
    created = new_rows(before, after, QrCode)
    assert len(created) == 1
    stored = created[0]
    assert stored == {
        "id": qr.pk, "makerspace_id": lab.home.pk, "target_type": "asset",
        "target_id": lab.asset.pk, "payload": qr.payload, "status": "active",
        "created_by_id": lab.actor.pk, "revoked_at": None,
        "created_at": qr.created_at, "updated_at": qr.updated_at,
    }
    events = new_rows(before, after, AuditLog)
    assert len(events) == 1
    assert_event(events[0], lab.actor, lab.home, qr, "qr.created", {})
    assert after == {**before, "boxes.qrcode": [*before["boxes.qrcode"], stored],
                     "audit.auditlog": [*before["audit.auditlog"], events[0]]}
    return after
