"""AssetQr creation, reuse, and rollback preserve their original HTTP contract."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import module_enabled
from tests.qr_asset_race_safety.helpers import (
    assert_created, asset_http, lab, state,
)
from tests.qr_target_safety_helpers import fail_after_insert

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("qr_management", [True, False], ids=["ordinary", "legacy-core-key-absent"])
def test_create_once_and_reuse_201_without_update_or_extra_audit(lab, qr_management):
    if not qr_management:
        # A persisted legacy row may lack a core key. Ordinary model saves restore
        # it; construct the row directly, leaving every production guard enabled.
        modules = [key for key in lab.home.enabled_modules if key != "qr_management"]
        Makerspace.objects.filter(pk=lab.home.pk).update(enabled_modules=modules)
        lab.home.refresh_from_db()
        assert not module_enabled(lab.home, "qr_management")
        assert module_enabled(lab.home, "asset_units")
    before = state()
    with CaptureQueriesContext(connection) as queries:
        response = asset_http(lab)
    after = assert_created(lab, before, response)
    assert not [q["sql"] for q in queries if q["sql"].startswith('UPDATE "boxes_qrcode"')]

    with CaptureQueriesContext(connection) as repeated_queries:
        reused = asset_http(lab)
    assert reused.status_code == 201, reused.data
    assert reused.data == response.data
    assert state() == after
    assert not [q["sql"] for q in repeated_queries
                if q["sql"].startswith(("INSERT ", "UPDATE ", "DELETE "))
                and any(f'"{table}"' in q["sql"] for table in
                        ("boxes_qrcode", "audit_auditlog", "inventory_inventoryasset"))]


def test_real_audit_insert_then_exception_rolls_back_qr_and_audit(lab, monkeypatch):
    before = state()
    inserted = fail_after_insert(monkeypatch, "qr.created")
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(RuntimeError, match="after real audit INSERT"):
            asset_http(lab)
    assert len(inserted) == 1
    assert any(q["sql"].startswith('INSERT INTO "boxes_qrcode"') for q in queries)
    assert any(q["sql"].startswith('INSERT INTO "audit_auditlog"') for q in queries)
    assert not AuditLog.objects.filter(pk=inserted[0]).exists()
    assert state() == before
