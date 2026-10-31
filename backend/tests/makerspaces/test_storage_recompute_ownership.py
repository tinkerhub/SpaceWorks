"""Real lock identity, continuity and top-level caller admission."""
from contextlib import contextmanager
from io import StringIO

import psycopg2
import pytest
from django.db import connection, connections, transaction

from apps.makerspaces.models import Makerspace
from apps.tenant_migration import gate_locks
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_runtime import (
    _exclusive_boundary_connection, assert_boundary_held, assert_write_allowed,
    boundary_tenant_write, tenant_write,
)
from tests.makerspaces.storage_recompute_faults import instrument
from tests.makerspaces.storage_recompute_support import (
    NS, await_lock, counter, locks, recompute, sql, storage_case,
)
from tests.tenant_migration.source_gate_helpers import make_space

pytestmark = pytest.mark.django_db(transaction=True)


@contextmanager
def disabled_autocommit():
    connection.set_autocommit(False)
    try:
        yield
    finally:
        connection.rollback()
        connection.set_autocommit(True)


@pytest.mark.parametrize("caller", [
    "same-shared", "different-shared", "exclusive", "unscoped", "atomic", "autocommit-false",
])
def test_exclusive_recompute_refuses_nesting_before_new_connection_or_provider(
    storage_case, monkeypatch, caller,
):
    case = storage_case
    Makerspace.objects.filter(pk=case.space.pk).update(storage_bytes_used=321)
    other = make_space("recompute-nesting-other")
    opened = instrument(monkeypatch)
    contexts = {
        "same-shared": lambda: boundary_tenant_write(case.space.pk),
        "different-shared": lambda: boundary_tenant_write(other.pk),
        "exclusive": lambda: boundary_tenant_write(case.space.pk, exclusive=True),
        "unscoped": gate_locks.unscoped_writer_shared_boundary,
        "atomic": transaction.atomic,
        "autocommit-false": disabled_autocommit,
    }
    with contexts[caller]():
        before = len(opened)
        with pytest.raises(SourceMigrationGateUnavailable, match="top-level"):
            recompute(case.space)
        assert len(opened) == before, "Refusal must precede new dedicated-connection I/O"
        assert case.store.calls == [] and counter(case.space) == 321
    assert locks(case.space.pk) == [] and locks(other.pk) == [] and locks(0) == []


def test_nested_ordinary_shared_guards_reuse_original_actual_exclusive_backend(storage_case, monkeypatch):
    space = storage_case.space
    opened = instrument(monkeypatch)
    with boundary_tenant_write(space.pk, exclusive=True):
        retained = _exclusive_boundary_connection(space.pk)
        pid = retained.raw.get_backend_pid()
        with boundary_tenant_write(space.pk), tenant_write(space.pk):
            assert_boundary_held(space.pk)
            assert_write_allowed(space.pk)
            assert _exclusive_boundary_connection(space.pk) is retained
            assert locks(space.pk) == [(pid, "ExclusiveLock", True, 2, [])]
        assert len(opened) == 1 and not retained.raw.closed
    assert retained.raw.closed and locks(space.pk) == []


@pytest.mark.parametrize("wrong", ["namespace", "key", "mode", "objsubid"])
def test_real_wrong_lock_does_not_substitute_for_original_exact_owner(storage_case, wrong):
    space = storage_case.space
    with boundary_tenant_write(space.pk, exclusive=True):
        retained = _exclusive_boundary_connection(space.pk)
        pid = retained.get_backend_pid()
        retained.rollback()
        namespace = NS + (wrong == "namespace")
        key = space.pk + (wrong == "key")
        mode = "ShareLock" if wrong == "mode" else "ExclusiveLock"
        with retained.cursor() as cursor:
            if wrong == "objsubid":
                cursor.execute("SELECT pg_advisory_lock(%s::bigint)", [(NS << 32) | space.pk])
            else:
                function = "pg_advisory_lock_shared" if wrong == "mode" else "pg_advisory_lock"
                cursor.execute(f"SELECT {function}(%s, %s)", [namespace, key])
        # Observe the actual wrong granted lock, not fabricated verifier results.
        observed = sql("""SELECT classid, objid, objsubid, mode, granted FROM pg_locks
                          WHERE pid=%s AND locktype='advisory'""", [pid])
        assert observed == [(namespace, key, 1 if wrong == "objsubid" else 2, mode, True)]
        with pytest.raises(SourceMigrationGateUnavailable, match="lost"):
            assert_boundary_held(space.pk)
        with pytest.raises(SourceMigrationGateUnavailable):
            _exclusive_boundary_connection(space.pk)
    assert locks(space.pk) == []


def test_real_different_backend_with_exact_lock_cannot_be_adopted(storage_case, monkeypatch):
    space = storage_case.space
    opened = instrument(monkeypatch)
    impostor = psycopg2.connect(**connections["default"].get_connection_params())
    try:
        with boundary_tenant_write(space.pk, exclusive=True):
            retained = _exclusive_boundary_connection(space.pk)
            original_pid = retained.raw.get_backend_pid()
            retained.raw.rollback()
            with impostor.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute("SELECT pg_advisory_xact_lock(%s,%s)", [NS, space.pk])
            assert await_lock(space.pk, "ExclusiveLock", granted=True) == impostor.get_backend_pid()
            assert original_pid != impostor.get_backend_pid()
            # Deliberate transport misrouting: query real locks on the replacement
            # backend. The verifier must reject its true PID despite an exact lock.
            retained.cursor_backend = impostor
            with pytest.raises(SourceMigrationGateUnavailable, match="lost"):
                _exclusive_boundary_connection(space.pk)
            assert len(opened) == 1
    finally:
        impostor.rollback()
        impostor.close()
    assert locks(space.pk) == []


@pytest.mark.parametrize("substitute", ["session", "new-transaction"])
def test_ended_transaction_cannot_be_hidden_by_same_pid_exact_substitute_lock(storage_case, substitute):
    """A matching pg_locks row alone does not prove uninterrupted ownership.

    Keep this a strict regression test: current source records no transaction
    identity, so static inspection predicts it will accept these substitutes.
    No private owner flags or verifier return values are changed by the test.
    """
    space = storage_case.space
    with boundary_tenant_write(space.pk, exclusive=True):
        retained = _exclusive_boundary_connection(space.pk)
        original_pid = retained.get_backend_pid()
        retained.commit()
        assert locks(space.pk) == []
        with retained.cursor() as cursor:
            function = "pg_advisory_lock" if substitute == "session" else "pg_advisory_xact_lock"
            cursor.execute(f"SELECT {function}(%s,%s)", [NS, space.pk])
        assert locks(space.pk) == [(original_pid, "ExclusiveLock", True, 2, [])]
        with pytest.raises(SourceMigrationGateUnavailable, match="lost|ended"):
            assert_boundary_held(space.pk)
    assert locks(space.pk) == []


def test_actual_closed_connection_during_acquisition_refuses_without_retry(storage_case, monkeypatch):
    case = storage_case
    original, opened = gate_locks._new_lock_connection, []

    def closed_transport():
        raw = original()
        opened.append(raw)
        raw.close()
        return raw

    monkeypatch.setattr(gate_locks, "_new_lock_connection", closed_transport)
    output = StringIO()
    with pytest.raises(SourceMigrationGateUnavailable):
        recompute(case.space, output)
    assert len(opened) == 1 and opened[0].closed
    assert case.store.calls == [] and counter(case.space) == 0
    assert "total=" not in output.getvalue() and locks(case.space.pk) == []
