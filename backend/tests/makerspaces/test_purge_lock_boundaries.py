"""Real lock contention, lost proof, and callbacks under synchronous ownership."""

from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.backup.operation_lock import OperationLockUnavailable, deployment_operation_lock
from apps.inventory import public_image_storage
from apps.makerspaces import lifecycle_purge, purge_locks, purge_storage
from apps.makerspaces.models import Makerspace, PurgeReceipt
from apps.makerspaces.purge_cleanup import owns_cleanup, synchronous_cleanup
from apps.makerspaces.purge_locks import PurgeBusy, purge_boundary
from apps.makerspaces.purge_receipts import retry_cleanup
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from tests.makerspaces.purge_test_support import (
    actor, advisory_lock, archived_space, arm, purge_clock, purge_store, receipt,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("key_kind", ["unscoped", "source", "another_tenant"])
def test_receipt_exclusion_conflicts_with_every_writer(key_kind, purge_store):
    user, row = actor(), receipt()
    other = Makerspace.objects.create(name="other", slug="other")
    key = {"unscoped": 0, "source": row.source_makerspace_id, "another_tenant": other.pk}[key_kind]
    with advisory_lock(key, shared=True) as acquired:
        assert acquired
        with pytest.raises(PurgeBusy):
            retry_cleanup(row.pk, user)
    assert not purge_store.calls and not purge_store.deletes
    assert PurgeReceipt.objects.get(pk=row.pk).last_attempt_at is None


def test_host_operation_busy_refuses_without_provider_access(purge_store):
    user, row = actor(), receipt()
    with deployment_operation_lock():
        with pytest.raises(OperationLockUnavailable):
            retry_cleanup(row.pk, user)
    assert purge_store.calls == []


def test_inventory_change_under_host_lock_refuses_before_first_delete(purge_store):
    user, row = actor(), receipt()
    key = f"evidence/{row.source_makerspace_id}/late"
    purge_store.put(purge_storage.bucket_name("private"), key)

    def new_tenant(_params):
        purge_store.on_list = None
        Makerspace.objects.create(name="new while fenced", slug="new-while-fenced")
        with pytest.raises(OperationLockUnavailable), deployment_operation_lock():
            pytest.fail("host operation lock was released during namespace enumeration")

    purge_store.on_list = new_tenant
    with pytest.raises(PurgeBusy, match="inventory changed"):
        retry_cleanup(row.pk, user)
    assert purge_store.has_key(purge_storage.bucket_name("private"), key)
    assert not purge_store.deletes


def test_lost_real_lock_connection_refuses_before_any_bytes(purge_store, purge_clock, monkeypatch):
    user, space = actor(), archived_space()
    arm(space, user, purge_clock)
    original = purge_locks._new_lock_connection
    opened = []

    def remember():
        db = original()
        opened.append(db)
        return db

    monkeypatch.setattr(purge_locks, "_new_lock_connection", remember)

    def lose_proof(_params):
        opened[0].rollback()  # Release the actual advisory xact locks, no fake verify.
        purge_store.on_list = None

    purge_store.on_list = lose_proof
    with pytest.raises(SourceMigrationGateUnavailable):
        lifecycle_purge.purge(space, user)
    assert Makerspace.objects.filter(pk=space.pk).exists()
    assert not purge_store.deletes and not PurgeReceipt.objects.exists()


def test_purge_boundary_refuses_atomic_caller_instead_of_self_deadlocking(purge_store):
    with transaction.atomic(), pytest.raises(ValidationError, match="non-transactional"):
        with purge_boundary(123):
            pytest.fail("atomic caller acquired purge authority")
    assert not connection.in_atomic_block


def test_purge_uses_strict_storage_without_storage_guard_under_maker_row(
    purge_store, purge_clock, monkeypatch,
):
    import apps.object_storage_lifecycle as storage_lifecycle

    user, space = actor(), archived_space()
    arm(space, user, purge_clock)
    guard = Mock(side_effect=AssertionError("purge acquired a storage guard under Maker lock"))
    monkeypatch.setattr(storage_lifecycle.StorageGuard, "acquire", guard)
    lifecycle_purge.purge(space, user)
    guard.assert_not_called()


def test_initial_retry_refuses_busy_source_before_provider_calls(purge_store, purge_clock):
    user, space = actor(), archived_space()
    arm(space, user, purge_clock)
    purge_store.calls.clear()
    with advisory_lock(space.pk, shared=True) as acquired:
        assert acquired
        with pytest.raises(PurgeBusy):
            lifecycle_purge.purge(space, user)
    assert not purge_store.calls
    assert Makerspace.objects.filter(pk=space.pk).exists()


def test_cleanup_suppression_happens_at_dispatch_and_resets_after_exception(monkeypatch, purge_store):
    space = archived_space()
    other = archived_space("survivor", storage_bytes_used=91)
    callbacks = []
    monkeypatch.setattr(transaction, "on_commit", callbacks.append)
    guard = Mock()
    try:
        with purge_boundary(space.pk, all_tenants=True) as verify, synchronous_cleanup(space.pk, verify=verify):
            assert owns_cleanup(space.pk) and not owns_cleanup(other.pk)
            public_image_storage.release_public_image_on_commit(space, "items/1/owned", guard=guard)
            public_image_storage.delete_public_image_on_commit(space, "items/1/owned", guard=guard)
            assert callbacks == []
            guard.verify.assert_not_called()
            public_image_storage.delete_public_image_on_commit(other, "items/2/survives", guard=guard)
            assert len(callbacks) == 1
            raise RuntimeError("graph rolled back")
    except RuntimeError:
        pass
    assert not owns_cleanup(space.pk)
    public_image_storage.release_public_image_on_commit(space, "items/1/owned", guard=guard)
    assert len(callbacks) == 2
    other.refresh_from_db()
    assert other.storage_bytes_used == 91
