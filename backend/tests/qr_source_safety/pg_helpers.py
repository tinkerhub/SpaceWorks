"""Bind full SQL to real backend advisory/row waits, using the stable Worker."""
from contextlib import contextmanager

from django.db import connection, transaction

from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE as NAMESPACE
from tests.box_parent_safety.pg_helpers import blocked_by, workers
from tests.box_parent_safety.test_source_order import source_select, try_exclusive

ROW_TABLES = ("makerspaces_makerspace", "boxes_qrcode", "inventory_inventoryasset",
              "inventory_inventoryproduct")


def row_lock(statement):
    return (any(f'FROM "{table}"' in statement.sql for table in ROW_TABLES)
            and "FOR " in statement.sql)


def table_lock(table):
    return lambda statement: f'FROM "{table}"' in statement.sql and "FOR UPDATE" in statement.sql


def audit_insert(statement):
    return statement.sql.startswith('INSERT INTO "audit_auditlog"')


def locks(tenant_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pid, mode, granted FROM pg_locks WHERE locktype='advisory' "
            "AND classid=%s AND objid=%s AND objsubid=2 ORDER BY pid, mode",
            [NAMESPACE, tenant_id],
        )
        return set(cursor.fetchall())


def assert_shared(pid, tenant_id):
    assert (pid, "ShareLock", True) in locks(tenant_id)


@contextmanager
def exclusive(tenant_id):
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s), pg_backend_pid()",
                           [NAMESPACE, tenant_id])
            pid = cursor.fetchone()[1]
        assert (pid, "ExclusiveLock", True) in locks(tenant_id)
        yield pid


def atomic_request(operation):
    """Supported existing outer SQL transaction: N and row SQL share a proven PID."""
    def call():
        with transaction.atomic():
            return operation()
    return call


def source_wait(worker, owner, tenant_id):
    pending = blocked_by(worker, owner, lambda sql: source_select(sql, tenant_id))
    assert pending.pid == worker.pid
    assert (owner, "ExclusiveLock", True) in locks(tenant_id)
    assert (worker.pid, "ShareLock", False) in locks(tenant_id)
    assert not any(row_lock(sql) for sql in worker.statements)
    return pending
