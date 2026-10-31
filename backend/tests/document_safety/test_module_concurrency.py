"""Real module uninstall winner orders and finite quota's second Maker lock."""
import pytest
from django.db import connection, transaction

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.makerspaces.module_install import uninstall_module
from tests.document_safety.helpers import (
    accepted_body, assert_storage_boundary, finalize, jwt_client, lab, presign, usage,
)
from tests.document_safety.pg_helpers import assert_no_maker_upgrade, race, statement
from tests.document_safety.test_warranty import host_url

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("operation", ["receipt-document", "machine-document", "machine-upsert"])
@pytest.mark.parametrize("uninstall_first", [False, True])
def test_actual_module_uninstall_both_winner_orders_preserve_locked_refusal(
    operation, uninstall_first, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, "receipt" if operation.startswith("receipt") else "machine")
    body = accepted_body("application/pdf")
    if operation.endswith("document"):
        key, _ = presign(case)
        case.store.seed(case.module.staging_key(key), body)
        action = "procurement.receipt_added" if operation.startswith("receipt") else "warranty.document_added"
        def write():
            return jwt_client(case.actor).post(
                case.url, {"object_key": key, "original_filename": "bill.pdf"}, format="json",
            )
    else:
        action = "warranty.updated"
        def write():
            return jwt_client(case.actor).put(host_url(case), {"vendor_name": "Winner"}, format="json")

    def disable():
        return uninstall_module(case.home, case.module_key, case.actor)

    before = AuditLog.objects.filter(action=action).count()
    first, second, captured, _, _ = race(
        disable if uninstall_first else write, write if uninstall_first else disable,
        pause_after=statement("makerspaces_makerspace", "FOR UPDATE" if uninstall_first else "FOR NO KEY UPDATE"),
        table="makerspaces_makerspace", clause="FOR NO KEY UPDATE" if uninstall_first else "FOR UPDATE",
    )
    written, disabled = (second, first) if uninstall_first else (first, second)
    assert disabled == [case.module_key]
    if uninstall_first:
        assert written.status_code == 400 and "module" in written.data, written.data
        assert AuditLog.objects.filter(action=action).count() == before
        assert usage(case) == 0
        if operation.endswith("document"):
            assert not case.model.objects.filter(object_key=key).exists()
            assert case.store.objects[key][0] == body
        else:
            case.target.refresh_from_db()
            assert case.target.vendor_name == ""
    else:
        assert written.status_code == (201 if operation.endswith("document") else 200), written.data
        assert AuditLog.objects.filter(action=action).count() == before + 1
        if operation.endswith("document"):
            assert usage(case) == len(body)
            assert case.model.objects.filter(object_key=key).count() == 1
    assert_no_maker_upgrade(captured, "second" if uninstall_first else "first")
    case.home.refresh_from_db()
    assert case.module_key not in case.home.enabled_modules
    assert AuditLog.objects.filter(action="makerspace.capabilities_changed").count() == 1


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
def test_new_document_metadata_and_finite_debit_never_upgrade_maker_fk_lock(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    data = accepted_body("application/pdf")
    case.store.seed(case.module.staging_key(key), data)
    case.store.boundary = lambda: assert_storage_boundary(case)
    target_table = "procurement_tobuyitem" if kind == "receipt" else "warranty_warranty"

    def hold_target_with_real_audit_fk():
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            type(case.target).objects.select_for_update().get(pk=case.target.pk)
            audit.record(case.actor, "document_safety.lock_holder", makerspace=case.home, target=case.target)
        return True

    def attach():
        return jwt_client(case.actor).post(
            case.url, {"object_key": key, "original_filename": "bill.pdf"}, format="json",
        )

    first, second, captured, _, _ = race(
        hold_target_with_real_audit_fk, attach,
        pause_after=lambda sql: sql.startswith('INSERT INTO "audit_auditlog"'),
        table=target_table, clause="FOR UPDATE",
    )
    assert first is True and second.status_code == 201, second.data
    assert_no_maker_upgrade(captured, "second")
    locks = [sql for sql, _ in captured["second"]
             if statement("makerspaces_makerspace", "FOR NO KEY UPDATE")(sql)]
    assert len(locks) >= 2, locks
    assert usage(case) == len(data)
    assert case.model.objects.filter(object_key=key).count() == 1
