"""Tenant-wide storage lifecycle exclusion, independent of application transactions."""
from contextlib import contextmanager

import psycopg2
from django.db import connection, connections

from apps.evidence.storage import StorageUnavailable
from apps.tenant_migration.gate_runtime import boundary_tenant_write

NAMESPACE = 734_312


def _new_lock_connection():
    params = connections["default"].get_connection_params()
    params["connect_timeout"] = 5
    return psycopg2.connect(**params)


class StorageGuard:
    def __init__(self, makerspace_id):
        self.makerspace_id = int(makerspace_id)
        self.connection = None
        self.backend_pid = None

    def verify(self, makerspace_id=None):
        if makerspace_id is not None and int(makerspace_id) != self.makerspace_id:
            raise StorageUnavailable
        try:
            if self.connection is None:
                raise RuntimeError("Storage guard is no longer held.")
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """SELECT pg_backend_pid(), EXISTS (
                        SELECT 1 FROM pg_locks WHERE locktype = 'advisory'
                        AND pid = pg_backend_pid() AND classid = %s AND objid = %s
                        AND objsubid = 2 AND mode = 'ExclusiveLock' AND granted)""",
                    [NAMESPACE, self.makerspace_id],
                )
                pid, held = cursor.fetchone()
                if pid != self.backend_pid or not held:
                    raise RuntimeError("Storage lock continuity was lost.")
        except Exception as exc:
            raise StorageUnavailable from exc
        return self

    def acquire(self):
        try:
            self.connection = _new_lock_connection()
            self.connection.autocommit = False
            with self.connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '6s'")
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s, %s), pg_backend_pid()",
                    [NAMESPACE, self.makerspace_id],
                )
                self.backend_pid = cursor.fetchone()[1]
            self.verify()
        except Exception as exc:
            try:
                self.close()
            except Exception:
                pass
            raise StorageUnavailable from exc

    def close(self):
        conn, self.connection = self.connection, None
        if conn is not None:
            try:
                conn.rollback()
            finally:
                conn.close()


@contextmanager
def storage_lifecycle(makerspace_id, *, guard=None):
    """Source boundary FIRST, then storage guard, then caller's domain row locks.

    Nested callers must pass ownership explicitly. A fresh acquisition inside an
    application atomic block is refused instead of risking a SQL/advisory deadlock.
    """
    if guard is not None:
        yield guard.verify(makerspace_id)
        return
    if connection.in_atomic_block:
        raise StorageUnavailable
    with boundary_tenant_write(makerspace_id):
        owned = StorageGuard(makerspace_id)
        try:
            owned.acquire()
            yield owned
        finally:
            try:
                owned.close()
            except Exception as exc:
                raise StorageUnavailable from exc
