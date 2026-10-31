"""Actual source-lock identities, full SQL and bounded event-driven checkpoints."""
import json
import threading
import time

from django.db import connection, transaction

from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE, acquire_exclusive
from tests.box_parent_safety.pg_helpers import blocked_by
from tests.qr_http_ownership_safety.p_observations import identity, source_locks

IDENTITY_TABLES = ('"accounts_user"', '"makerspaces_makerspacemembership"',
                   '"accounts_memberclaimcode"')


def row_lock(sql):
    return "FOR UPDATE" in sql and any(f'FROM {table}' in sql for table in IDENTITY_TABLES)


def source_statement(statement):
    return ("pg_advisory_xact_lock(" in statement.sql
            and statement.params[0] == SOURCE_GATE_LOCK_NAMESPACE)


def exclusive_n(key):
    with transaction.atomic():
        acquire_exclusive(key)
    return "exclusive N acquired"


class NProof:
    def __init__(self, keys, record_property):
        self.keys = set(keys)
        assert 0 not in self.keys
        self.record = record_property
        self.original = None
        self.activity_identity = None

    def observe(self, label):
        rows = source_locks()
        owned = [row for row in rows if row["objid"] in self.keys
                 and row["mode"] == "ShareLock" and row["granted"]]
        assert sorted(row["objid"] for row in owned) == sorted(self.keys), rows
        identities = {row["objid"]: identity(row) for row in owned}
        if self.original is None:
            self.original = identities
        assert identities == self.original, (self.original, rows)
        metadata = []
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            for lock in owned:
                cursor.execute("SELECT pid, datid, backend_start, xact_start, state, query "
                    "FROM pg_stat_activity WHERE pid=%s AND datname=current_database()", [lock["pid"]])
                values = cursor.fetchone()
                assert values is not None and values[0] == lock["pid"]
                assert values[1] == lock["database"] and values[3] is not None
                metadata.append(values)
        activity_identity = {row[0]: (row[2], row[3]) for row in metadata}
        if self.activity_identity is None:
            self.activity_identity = activity_identity
        assert activity_identity == self.activity_identity
        self.record(f"N_{label}", json.dumps({"locks": rows, "owned_activity": metadata}, default=str))
        return {row["objid"]: row["pid"] for row in owned}

    def queued(self, exclusive, key):
        owner_pid = self.original[key][0]
        statement = blocked_by(exclusive, owner_pid, source_statement)
        assert statement.params == (SOURCE_GATE_LOCK_NAMESPACE, key)
        pending = [row for row in source_locks() if row["pid"] == exclusive.pid
                   and row["objid"] == key and row["mode"] == "ExclusiveLock"
                   and not row["granted"] and owner_pid in row["blockers"]]
        assert len(pending) == 1
        self.record("queued_exclusive_N", json.dumps({"full_statement": vars(statement),
            "pending": pending, "original": self.original[key]}, default=str))

    def released(self):
        assert self.original
        assert not [row for row in source_locks() if row["granted"]
                    and identity(row) in self.original.values()]


class Checkpoint:
    def __init__(self):
        self.reached, self.release = threading.Event(), threading.Event()

    def stop(self):
        self.reached.set()
        assert self.release.wait(20), "Unreleased claim-source checkpoint"

    def wait(self, worker):
        assert self.reached.wait(10), (worker.error, worker.statements)
        assert worker.error is None


class TransitionProbe:
    """Pause before the first target lock, after real tenant audit, and at commit."""
    def __init__(self):
        self.before_rows, self.audit, self.commit = (Checkpoint() for _ in range(3))
        self.sql = []

    def capture(self, execute, sql, params, many, context):
        row = {"sql": sql, "params": tuple(params or ()), "completed": False,
               "pid": context["connection"].connection.info.backend_pid}
        self.sql.append(row)
        if row_lock(sql) and not self.before_rows.reached.is_set():
            self.before_rows.stop()
        result = execute(sql, params, many, context)
        row["completed"] = True
        # AuditLog INSERT has a makerspace_id parameter; identify the canonical
        # tenant event by its action, without depending on column order or SQL width.
        if (sql.startswith('INSERT INTO "audit_auditlog"')
                and "presence.ended_claim_revoked" in row["params"]
                and not self.audit.reached.is_set()):
            connection.on_commit(self.commit.stop)
            self.audit.stop()
        return result

    def run(self, operation):
        def observed():
            with connection.execute_wrapper(self.capture):
                return operation()
        return observed

    def release_all(self):
        for step in (self.before_rows, self.audit, self.commit):
            step.release.set()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release_all()


def wait_raw_n(key, blocker_pid, baseline, record_property):
    """Find a real newly queued dedicated backend; activity query is metadata only."""
    deadline, poll = time.monotonic() + 10, threading.Event()
    while time.monotonic() < deadline:
        pending = [row for row in source_locks() if row["objid"] == key
                   and row["mode"] == "ShareLock" and not row["granted"]
                   and identity(row) not in baseline and blocker_pid in row["blockers"]]
        if pending:
            assert len(pending) == 1, pending
            row = pending[0]
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute("SELECT pid, backend_start, xact_start, query FROM pg_stat_activity "
                               "WHERE pid=%s AND datname=current_database()", [row["pid"]])
                metadata = cursor.fetchone()
            assert metadata and metadata[0] == row["pid"]
            record_property("actual_N_wait", json.dumps({"lock": row, "activity": metadata}, default=str))
            return row["pid"]
        poll.wait(0.01)
    raise AssertionError(("No owned raw N wait edge", key, blocker_pid, source_locks()))
