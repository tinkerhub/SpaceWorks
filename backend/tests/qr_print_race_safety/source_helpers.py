"""Raw exclusive Source N holder; observed HTTP work uses an outer SQL atomic."""
from contextlib import contextmanager

import psycopg2
from django.db import connection, connections, transaction

from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE as NAMESPACE


def source_select(statement, tenant_id):
    return ("pg_advisory_xact_lock_shared(" in statement.sql
            and statement.params == (NAMESPACE, tenant_id))


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
    # A separate raw backend owns only N; no application transaction is faked.
    raw = psycopg2.connect(**connections["default"].get_connection_params())
    try:
        raw.autocommit = False
        with raw.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s), pg_backend_pid()",
                           [NAMESPACE, tenant_id])
            pid = cursor.fetchone()[1]
        assert (pid, "ExclusiveLock", True) in locks(tenant_id)
        yield pid
    finally:
        try:
            raw.rollback()
        finally:
            raw.close()


def try_exclusive(tenant_id):
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s)",
                           [NAMESPACE, tenant_id])
            acquired = cursor.fetchone()[0]
        transaction.set_rollback(True)
    return acquired


def atomic_request(operation):
    def call():
        # Without this, middleware owns N on a dedicated raw connection: its PID
        # cannot be inferred from Worker.pid or observed by Django's SQL wrapper.
        with transaction.atomic():
            return operation()
    return call
