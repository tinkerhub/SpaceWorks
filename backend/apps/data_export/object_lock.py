"""Serialize export upload and deletion without transacting application I/O."""

import hashlib
from contextlib import contextmanager

import psycopg2
from django.db import connections


EXPORT_OBJECT_LOCK_NAMESPACE = 734_311


@contextmanager
def export_object_lock(object_key, *, blocking=True):
    # A collision only serializes unrelated exports; it never grants ownership.
    key = int.from_bytes(hashlib.sha256(object_key.encode()).digest()[:4], signed=True)
    lock_connection = psycopg2.connect(**connections["default"].get_connection_params())
    try:
        lock_connection.autocommit = False
        with lock_connection.cursor() as cursor:
            function = "pg_advisory_xact_lock" if blocking else "pg_try_advisory_xact_lock"
            cursor.execute(
                f"SELECT {function}(%s, %s), pg_backend_pid()",
                [EXPORT_OBJECT_LOCK_NAMESPACE, key],
            )
            result, backend_pid = cursor.fetchone()
            acquired = blocking or bool(result)
            if acquired:
                cursor.execute(
                    """SELECT pg_backend_pid(), EXISTS (
                        SELECT 1 FROM pg_locks WHERE locktype = 'advisory'
                        AND pid = pg_backend_pid() AND classid = %s::oid AND objid = %s::oid
                        AND objsubid = 2 AND mode = 'ExclusiveLock' AND granted
                    )""",
                    [EXPORT_OBJECT_LOCK_NAMESPACE, key & 0xFFFFFFFF],
                )
                retained_pid, held = cursor.fetchone()
                if retained_pid != backend_pid or not held:
                    raise RuntimeError("The export object lock was not retained.")
        yield acquired
    finally:
        try:
            lock_connection.rollback()
        finally:
            lock_connection.close()
