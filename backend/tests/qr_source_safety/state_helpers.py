"""Whole persisted rows, including binary audit columns and native attempt history."""
from django.contrib.admin.models import LogEntry

from apps.audit.models import AuditLog
from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.inventory.models import Category, InventoryAsset, InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.operations.models import InventoryAdjustment, QrPrintBatch, QrPrintBatchItem
from apps.warranty.models import Warranty


def plain(value):
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def state(*, attempts=True):
    models = (Makerspace, Category, Box, BoxScan, InventoryProduct, InventoryAsset,
              QrCode, QrScanEvent, InventoryAdjustment, QrPrintBatch, QrPrintBatchItem,
              Warranty, AuditLog, *((LogEntry,) if attempts else ()))
    return {model._meta.label_lower: plain(list(model.objects.order_by("pk").values()))
            for model in models}


def audit_ids():
    return set(AuditLog.objects.values_list("pk", flat=True))


def audits_since(ids):
    return list(AuditLog.objects.exclude(pk__in=ids).order_by("pk"))


def assert_gate(response):
    assert response.status_code == 423, getattr(response, "data", response.content)
    assert response.json()["code"] == "tenant_migration_quiesced"


def assert_canonical(row, actor, qr, *, deleted=False):
    assert (row.action, row.actor_id, row.makerspace_id, row.target_type, row.target_id) == (
        "control.object_deleted" if deleted else "control.object_updated",
        actor.pk, qr.makerspace_id, "boxes.qrcode", str(qr.pk),
    )
    assert row.meta == ({"model": "boxes.qrcode"} if deleted else {
        "model": "boxes.qrcode", "changed_fields": ["created_by"], "detail": {},
    })
