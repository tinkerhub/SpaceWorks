"""Discover real P backends from live locks before consulting fresh activity stats."""
import json

from django.db import connection, transaction

from apps.tenant_migration.gate_locks import (
    SOURCE_GATE_LOCK_NAMESPACE, acquire_unscoped_writer_exclusive,
)
from tests.box_parent_safety.pg_helpers import blocked_by


def source_locks():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT l.*, pg_blocking_pids(l.pid) AS blockers FROM pg_locks l "
            "WHERE l.locktype='advisory' AND l.classid=%s AND l.objsubid=2 "
            "AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
            "ORDER BY l.objid, l.pid, l.mode",
            [SOURCE_GATE_LOCK_NAMESPACE],
        )
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def identity(row):
    return tuple(row[name] for name in ("pid", "database", "classid", "objid",
                                        "objsubid", "mode", "virtualtransaction"))


def exclusive_p():
    with transaction.atomic():
        acquire_unscoped_writer_exclusive()
        return "exclusive P acquired"


def p_statement(statement):
    return ("pg_advisory_xact_lock(" in statement.sql
            and statement.params == (SOURCE_GATE_LOCK_NAMESPACE, 0))


class PProof:
    def __init__(self, record_property):
        self.baseline = {identity(row) for row in source_locks()}
        self.record_property = record_property
        self.owner = None
        self.transaction = None
        self.backend_start = None
        self.xact_start = None
        self.history = []

    def observe(self, worker, label, *, no_n=False):
        # Never assume the app PID is P, or that a fresh backend is already in the
        # controller's cached pg_stat_activity snapshot. Discover live lock rows first.
        rows = source_locks()
        fresh = [row for row in rows if identity(row) not in self.baseline]
        shared = [row for row in fresh
                  if row["objid"] == 0 and row["mode"] == "ShareLock" and row["granted"]]
        assert len(shared) == 1, rows
        lock = shared[0]
        assert lock["pid"] != worker.pid
        if self.owner is None:
            self.owner, self.transaction = lock["pid"], identity(lock)
        assert lock["pid"] == self.owner and identity(lock) == self.transaction
        if no_n:
            assert not [row for row in fresh if row["objid"] != 0], rows
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT pid, datid, backend_start, xact_start, state, query "
                "FROM pg_stat_activity WHERE pid=%s AND datname=current_database()",
                [self.owner],
            )
            columns = [column[0] for column in cursor.description]
            activity = dict(zip(columns, cursor.fetchone()))
            cursor.execute("SELECT pg_backend_pid()")
            controller_pid = cursor.fetchone()[0]
        assert activity["pid"] == self.owner != controller_pid
        assert activity["datid"] == lock["database"]
        assert activity["state"] == "idle in transaction"
        assert activity["xact_start"] is not None
        if self.backend_start is None:
            self.backend_start, self.xact_start = activity["backend_start"], activity["xact_start"]
        assert (activity["backend_start"], activity["xact_start"]) == (self.backend_start, self.xact_start)
        assert "pg_backend_pid()" in activity["query"] and "pg_locks" in activity["query"]
        self.history.append({"checkpoint": label, "worker_pid": worker.pid,
                             "P": lock, "all_source_locks": rows, "P_activity": activity})
        self.record_property(f"P_{label}", json.dumps(self.history[-1], default=str))

    def blocked_exclusive(self, worker):
        pending = blocked_by(worker, self.owner, p_statement)
        rows = source_locks()
        waiter = [row for row in rows if row["pid"] == worker.pid and row["objid"] == 0
                  and row["mode"] == "ExclusiveLock" and not row["granted"]]
        assert len(waiter) == 1 and self.owner in waiter[0]["blockers"], rows
        self.record_property("P_exclusive_wait", json.dumps({
            "statement": vars(pending), "lock": waiter[0], "owner_pid": self.owner,
        }, default=str))

    def released(self):
        assert self.history
        assert not [row for row in source_locks()
                    if identity(row) == self.transaction and row["granted"]]
