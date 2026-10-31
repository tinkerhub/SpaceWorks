"""Native HTTP fixtures and SQL observations; all application locks remain real."""
from copy import deepcopy
import queue
import threading
import time

from django.db import close_old_connections, connection, connections, transaction

from apps.audit.models import AuditLog
from apps.boxes.models import QrScanEvent
from apps.makerspaces.models import Makerspace
from apps.operations.models import InventoryAdjustment
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from apps.warranty.models import Warranty, WarrantyDocument
from tests.document_safety.helpers import accepted_body, finalize, lab, presign
from tests.document_safety.pg_helpers import assert_no_maker_upgrade, statement
from tests.qr_target_safety_helpers import native_client, native_form, superadmin
from tests.tenant_migration.source_gate_helpers import close_gate


EDIT = {
    "vendor_name": "Native race vendor", "vendor_contact": "native@example.test",
    "purchased_on": "2025-03-04", "warranty_expires_on": "2029-03-04",
}


def native_case(monkeypatch, settings, kind="asset", *, documents=False):
    case = lab(monkeypatch, settings, kind)
    case.root = superadmin()
    case.native = native_client(case.root)
    case.kind = kind
    case.host = getattr(case.target, kind)
    if documents:
        key, _ = presign(case)
        body = accepted_body("application/pdf")
        case.store.seed(case.module.staging_key(key), body)
        response = finalize(case, key)
        assert response.status_code == 201, response.data
        doc = WarrantyDocument.objects.get(object_key=key)
        assert doc.warranty_id == case.target.pk and doc.size_bytes == len(body)
        assert key == doc.object_key and case.store.objects[key][0] == body
    case.document_rows = list(WarrantyDocument.objects.order_by("pk").values())
    case.provider_state = provider_state(case)
    return case


def provider_state(case):
    # Provider calls contain stream objects whose equality is identity-based.
    # The append-only call count detects any I/O; compare actual bytes/versions deeply.
    return len(case.store.calls), deepcopy((case.store.objects, case.store.versions))


def assert_documents_unchanged(case):
    assert list(WarrantyDocument.objects.order_by("pk").values()) == case.document_rows
    assert provider_state(case) == case.provider_state


def form(case, *, add=False, **changes):
    values = {"makerspace": case.home.pk, case.kind: case.host.pk} if add else {}
    values.update(changes)
    return native_form(case.native, "warranty_warranty", None if add else case.target, **values)


def locked_host(case, after_lock=lambda: None):
    """Actual transaction owner used to change admission only after a proven wait."""
    def operation():
        with transaction.atomic():
            type(case.host).objects.select_for_update().get(pk=case.host.pk)
            after_lock()
    return operation


def locked_maker(case, after_lock):
    def operation():
        with transaction.atomic():
            Makerspace.objects.select_for_update(no_key=True).get(pk=case.home.pk)
            after_lock()
    return operation


def source_locks():
    # Include dedicated source-boundary connections, which Django SQL capture cannot see.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pid, objid::bigint, mode FROM pg_locks WHERE locktype='advisory' "
            "AND classid=734310 AND objsubid=2 AND granted",
        )
        return set(cursor.fetchall())


def assert_source_pinned(case, queries):
    checks = [(sql, params) for sql, params in queries
              if 'FROM "tenant_migration_sourcemigrationgate"' in sql]
    assert checks, queries
    assert all(case.home.pk in params and case.other.pk not in params
               for _, params in checks), checks


def assert_native_lock_order(case, captured, worker, *, complete=True):
    queries = captured[worker]
    assert_no_maker_upgrade(captured, worker)
    maker = next(i for i, (sql, _) in enumerate(queries)
                 if statement("makerspaces_makerspace", "FOR NO KEY UPDATE")(sql))
    host = next(i for i, (sql, _) in enumerate(queries)
                if statement(case.host._meta.db_table, "FOR UPDATE")(sql))
    source = next(i for i, (sql, _) in enumerate(queries)
                  if 'FROM "tenant_migration_sourcemigrationgate"' in sql)
    assert source < maker < host, queries
    assert all(case.home.pk in params and case.other.pk not in params
               for sql, params in queries
               if statement("makerspaces_makerspace", "FOR NO KEY UPDATE")(sql)), queries
    host_sql, host_params = queries[host]
    assert '"makerspace_id" = %s' in host_sql and case.home.pk in host_params
    if complete:
        warranty = next(i for i, (sql, _) in enumerate(queries)
                        if statement("warranty_warranty", "FOR UPDATE")(sql))
        assert host < warranty, queries
    assert_source_pinned(case, queries)


def assert_native_audit(case, *, created=False):
    action = "control.object_created" if created else "control.object_updated"
    row = AuditLog.objects.get(action=action, target_type="warranty.warranty")
    assert row.actor_id == case.root.pk and row.makerspace_id == case.home.pk
    if not created:
        assert row.target_id == str(case.target.pk)
        assert row.meta["changed_fields"] == sorted(EDIT)
    assert row.meta["model"] == "warranty.warranty" and row.meta["detail"] == {}
    assert not AuditLog.objects.filter(action=action, makerspace=case.other).exists()
    return row


def assert_move_result(case, host, qr, product):
    host.refresh_from_db()
    qr.refresh_from_db()
    product.refresh_from_db()
    destination = host.product
    assert host.makerspace_id == qr.makerspace_id == destination.makerspace_id == case.other.pk
    assert qr.target_type == "asset" and qr.target_id == host.pk
    assert destination.pk != product.pk and product.makerspace_id == case.home.pk
    assert (product.total_quantity, product.available_quantity) == (0, 0)
    assert (destination.total_quantity, destination.available_quantity) == (1, 1)
    adjustments = list(InventoryAdjustment.objects.order_by("pk"))
    assert len(adjustments) == 2
    assert {(row.makerspace_id, row.product_id, row.delta_available) for row in adjustments} == {
        (case.home.pk, product.pk, -1), (case.other.pk, destination.pk, 1),
    }
    scan = QrScanEvent.objects.get(qr_code=qr)
    assert scan.context == QrScanEvent.Context.REASSIGNMENT
    assert scan.makerspace_id == case.other.pk and scan.actor_id == case.transfer_actor.pk
    moved = AuditLog.objects.get(action="inventory.asset_moved_makerspace")
    assert moved.actor_id == case.transfer_actor.pk and moved.makerspace_id == case.other.pk
    assert moved.target_type == "inventory.inventoryasset" and moved.target_id == str(host.pk)
    assert moved.meta["old_makerspace_id"] == case.home.pk
    assert moved.meta["new_makerspace_id"] == case.other.pk
    assert moved.meta["warranty_id"] == case.target.pk
    case.target.refresh_from_db()
    assert case.target.makerspace_id == case.other.pk and case.target.asset_id == host.pk
    case.target.full_clean()
    return moved


def frozen_source_wait(case, url, data):
    """Observe native's dedicated boundary PID waiting on a real exclusive owner.

    pg_helpers.race observes the application's SQL connection. Source boundaries
    intentionally use another connection, so this one schedule observes that PID
    directly; it never replaces a boundary, gate check, or lock acquisition.
    """
    assert connection.vendor == "postgresql", "Real PG required; no SQLite skip"
    assert connection.get_autocommit() and not connection.in_atomic_block
    ready, result = queue.Queue(), queue.Queue()
    captured, worker = [], None
    native_pid = boundary_pid = None

    def post():
        announced = False
        try:
            close_old_connections()
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout='8s'")
                cursor.execute("SET statement_timeout='12s'")
                cursor.execute("SELECT pg_backend_pid()")
                ready.put(cursor.fetchone()[0])
                announced = True

            def capture(execute, sql, params, many, context):
                captured.append((sql, params))
                return execute(sql, params, many, context)

            with connection.execute_wrapper(capture):
                result.put((case.native.post(url, data), None))
        except BaseException as exc:
            if not announced:
                ready.put(exc)
            result.put((None, exc))
        finally:
            connections.close_all()

    before = source_locks()
    try:
        with boundary_tenant_write(case.home.pk, exclusive=True):
            owners = source_locks() - before
            assert len(owners) == 1, owners
            owner_pid, tenant, mode = owners.pop()
            assert (tenant, mode) == (case.home.pk, "ExclusiveLock")
            worker = threading.Thread(target=post, daemon=True)
            worker.start()
            native_pid = ready.get(timeout=5)
            if isinstance(native_pid, BaseException):
                raise native_pid
            deadline, blocked = time.monotonic() + 5, None
            while time.monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT a.pid, a.query FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid "
                        "WHERE l.locktype='advisory' AND l.classid=734310 AND l.objid=%s "
                        "AND l.objsubid=2 AND NOT l.granted AND a.wait_event_type='Lock' "
                        "AND %s = ANY(pg_blocking_pids(a.pid))", [case.home.pk, owner_pid],
                    )
                    blocked = cursor.fetchone()
                if blocked:
                    break
                threading.Event().wait(0.01)
            assert blocked, "Native never waited on the actual exclusive source owner"
            boundary_pid, waited = blocked
            assert len({owner_pid, native_pid, boundary_pid}) == 3
            assert "pg_advisory_xact_lock_shared" in waited
            assert captured and not result.qsize()
            close_gate(case.home, case.root)
    finally:
        if worker:
            worker.join(timeout=20)
            if worker.is_alive():
                with connection.cursor() as cursor:
                    for pid in (native_pid, boundary_pid):
                        if type(pid) is int:
                            cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
                worker.join(timeout=5)
            assert not worker.is_alive(), "Owned native worker leaked"
    response, error = result.get(timeout=1)
    if error:
        raise error
    return response, captured, (owner_pid, native_pid, boundary_pid), waited
