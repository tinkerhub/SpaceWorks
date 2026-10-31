"""Real dedicated PostgreSQL transaction/retention behavior; never a guard stub."""
from threading import Event
from unittest.mock import Mock

import pytest
from django.db import connection, transaction

from apps import object_storage_lifecycle as lifecycle
from apps.evidence.storage import StorageUnavailable
from tests.atomic_publication.threading import workers
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db(transaction=True)


def test_dedicated_transaction_holds_independent_namespace_until_close():
    space = make_space("atomic-lock-namespace")
    guard = lifecycle.StorageGuard(space.pk)
    guard.acquire()
    try:
        assert lifecycle.NAMESPACE == 734312
        assert not connection.in_atomic_block
        assert guard.connection.autocommit is False
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            assert cursor.fetchone()[0] != guard.backend_pid
            cursor.execute("SELECT classid, objid, mode FROM pg_locks WHERE pid=%s AND locktype='advisory'", [guard.backend_pid])
            assert (734312, space.pk, "ExclusiveLock") in cursor.fetchall()
        with transaction.atomic(), connection.cursor() as cursor:
            # Source-gate and export locks do not alias storage exclusion.
            cursor.execute("SELECT pg_try_advisory_xact_lock(734310, %s), pg_try_advisory_xact_lock(734311, %s)", [space.pk, space.pk])
            assert cursor.fetchone() == (True, True)
        assert guard.verify(space.pk) is guard
    finally:
        guard.close()
    with pytest.raises(StorageUnavailable):
        guard.verify()


def test_contender_blocks_through_metadata_commit_and_then_enters():
    space = make_space("atomic-lock-commit")
    started, acquired = Event(), Event()
    with workers() as spawn:
        with lifecycle.storage_lifecycle(space.pk) as owned:
            def contender():
                started.set()
                with lifecycle.storage_lifecycle(space.pk) as second:
                    second.verify(space.pk)
                    acquired.set()
            future = spawn(contender)
            assert started.wait(3)
            assert not acquired.wait(0.15)
            with transaction.atomic():
                transaction.on_commit(lambda: (owned.verify(space.pk), acquired.is_set() and pytest.fail("guard released before callback")))
            assert not acquired.is_set()
        future.result(timeout=8)
    assert acquired.is_set()


def test_contender_busy_is_bounded_and_typed():
    space = make_space("atomic-lock-busy")
    with lifecycle.storage_lifecycle(space.pk):
        with workers() as spawn:
            def contender():
                with pytest.raises(StorageUnavailable):
                    with lifecycle.storage_lifecycle(space.pk):
                        pytest.fail("contender acquired held lock")
            spawn(contender).result(timeout=9)


def test_passed_guard_reuses_connection_inside_atomic_and_rejects_wrong_tenant(monkeypatch):
    space, other = make_space("atomic-reuse"), make_space("atomic-wrong")
    factory = Mock(wraps=lifecycle._new_lock_connection)
    monkeypatch.setattr(lifecycle, "_new_lock_connection", factory)
    with lifecycle.storage_lifecycle(space.pk) as owned:
        with transaction.atomic():
            with lifecycle.storage_lifecycle(space.pk, guard=owned) as reused:
                assert reused is owned
            with pytest.raises(StorageUnavailable):
                with lifecycle.storage_lifecycle(other.pk, guard=owned):
                    pytest.fail("foreign guard accepted")
        assert factory.call_count == 1
    with pytest.raises(StorageUnavailable):
        with lifecycle.storage_lifecycle(space.pk, guard=owned):
            pytest.fail("released guard accepted")
    assert factory.call_count == 1


def test_fresh_acquire_under_application_atomic_is_refused_before_open(monkeypatch):
    factory = Mock(side_effect=AssertionError("must not open exclusive connection"))
    monkeypatch.setattr(lifecycle, "_new_lock_connection", factory)
    with transaction.atomic(), pytest.raises(StorageUnavailable):
        with lifecycle.storage_lifecycle(1):
            pytest.fail("late lock acquisition accepted")
    factory.assert_not_called()


def test_backend_change_or_transaction_rollback_invalidates_retention():
    space = make_space("atomic-retention")
    guard = lifecycle.StorageGuard(space.pk)
    guard.acquire()
    try:
        actual_pid = guard.backend_pid
        guard.backend_pid += 1
        with pytest.raises(StorageUnavailable):
            guard.verify()
        guard.backend_pid = actual_pid
        guard.connection.rollback()
        with pytest.raises(StorageUnavailable):
            guard.verify()
    finally:
        guard.close()


def test_failed_dedicated_connection_is_typed_and_never_yields(monkeypatch):
    monkeypatch.setattr(lifecycle, "_new_lock_connection", Mock(side_effect=RuntimeError("pool unavailable")))
    with pytest.raises(StorageUnavailable):
        with lifecycle.storage_lifecycle(make_space("atomic-no-backend").pk):
            pytest.fail("failed guard yielded")
