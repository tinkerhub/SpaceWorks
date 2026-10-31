"""Observe the dedicated source backend through real PostgreSQL lock metadata."""
import threading
import time

from django.db import connection

from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE


def source_pids(tenant_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pid FROM pg_locks WHERE locktype = 'advisory' "
            "AND classid = %s AND objid = %s AND objsubid = 2",
            [SOURCE_GATE_LOCK_NAMESPACE, tenant_id],
        )
        return {row[0] for row in cursor.fetchall()}


def dedicated_waiter(worker, owner_pid, tenant_id, previous):
    """Exact tenant advisory key + newly owned PID + pg_blocking_pids edge."""
    deadline, poll = time.monotonic() + 10, threading.Event()
    while time.monotonic() < deadline:
        if worker.error:
            raise worker.error
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT l.pid, pg_blocking_pids(l.pid) FROM pg_locks l "
                "WHERE l.locktype = 'advisory' AND l.classid = %s AND l.objid = %s "
                "AND l.objsubid = 2 AND l.mode = 'ShareLock' AND NOT l.granted",
                [SOURCE_GATE_LOCK_NAMESPACE, tenant_id],
            )
            candidates = [r for r in cursor.fetchall() if r[0] not in previous]
        if candidates:
            assert len(candidates) == 1, candidates
            pid, blockers = candidates[0]
            assert pid not in {owner_pid, worker.pid}
            assert owner_pid in blockers
            # Activity information is cached within the controller transaction.
            # Discover the newly owned lock from live lock metadata first, then
            # refresh statistics before binding that exact PID to its real SQL.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute("SELECT query FROM pg_stat_activity WHERE pid = %s", [pid])
                activity = cursor.fetchone()
            assert activity is not None, pid
            sql = activity[0]
            assert "pg_advisory_xact_lock_shared(" in sql
            assert "pg_backend_pid()" in sql
            return pid, sql, blockers
        poll.wait(0.01)
    raise AssertionError(("No dedicated source wait edge", worker.pid, owner_pid, tenant_id))


def assert_source_shared_held(pid, tenant_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT mode, granted FROM pg_locks WHERE locktype = 'advisory' "
            "AND pid = %s AND classid = %s AND objid = %s AND objsubid = 2",
            [pid, SOURCE_GATE_LOCK_NAMESPACE, tenant_id],
        )
        assert ("ShareLock", True) in cursor.fetchall()
