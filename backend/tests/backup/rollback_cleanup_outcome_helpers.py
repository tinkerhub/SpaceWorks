"""Outcome fixtures: real database authority/locks, transport-only versioned store."""

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection

from apps.backup import rollback_cleanup, storage
from apps.backup.models import DeploymentRecoveryState, RestoreOperation, RestoreRollbackObject
from apps.backup.operation_lock import OperationLockUnavailable, deployment_operation_lock
from apps.backup.rollback_cleanup_outcomes import RollbackCleanupOutcomeUnavailable
from apps.makerspaces.purge_storage import bucket_name
from apps.tenant_migration.gate_locks import unscoped_writer_shared_boundary
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from tests.backup.test_restore_services import restore_fixture
from tests.makerspaces.module_cleanup_support import module_space, rollback
from tests.makerspaces.purge_test_support import advisory_lock


@pytest.fixture
def outcome_store(module_store, monkeypatch):
    strict_delete = module_store.delete_objects
    module_store.client_requests = []

    def delete_objects(*, Bucket, Delete):
        # Same exact-version fake semantics; trusted rollback uses Quiet=True.
        assert not connection.in_atomic_block
        assert Delete["Quiet"] is True
        return strict_delete(Bucket=Bucket, Delete={**Delete, "Quiet": False})

    def client():
        assert not connection.in_atomic_block
        module_store.client_requests.append(True)
        return module_store

    monkeypatch.setattr(module_store, "delete_objects", delete_objects)
    monkeypatch.setattr(storage, "client", client)
    return module_store


def recovery(mode=DeploymentRecoveryState.Mode.NORMAL, active=None, **values):
    # Root's migration-equivalent fixture owns singleton creation. Be explicit
    # about the cleanable baseline; never make a missing state normal on demand.
    assert DeploymentRecoveryState.objects.filter(pk=1).update(
        mode=mode, active_restore=active, **values,
    ) == 1
    return DeploymentRecoveryState.objects.get(pk=1)


def case(store, *, stage=RestoreOperation.Stage.COMPLETED, global_row=False, version_only=False):
    space = module_space(f"outcome-{uuid4().hex}", storage_bytes_used=100)
    # One restore per stage per test avoids restore_fixture's stage-based usernames.
    _, restore = restore_fixture(stage=stage)
    row = rollback(restore, None if global_row else space, "events", "private", "legacy/source", 7)
    bucket = bucket_name(row.bucket_kind)
    original = store.put(bucket, row.source_key, b"oldcopy")
    replacement = store.put(bucket, row.source_key, b"replacement")
    copies = set()
    if version_only:
        row.copy_key = ""
        row.source_version_id = original[2]
        row.replacement_version_id = replacement[2]
        row.size_bytes = 0  # Version-only rollback creates no extra charged copy.
        row.save(update_fields=("copy_key", "source_version_id", "replacement_version_id", "size_bytes"))
    else:
        copies.add(store.put(bucket, row.copy_key, b"oldcopy"))
        copies.add(store.put(bucket, row.copy_key, b"", marker=True))
    return SimpleNamespace(space=space, restore=restore, row=row, original=original,
                           replacement=replacement, copies=copies)


def snapshot(item, store):
    item.space.refresh_from_db()
    return SimpleNamespace(
        objects=dict(store.objects), calls=list(store.calls), clients=list(store.client_requests),
        row=RestoreRollbackObject.objects.values().get(pk=item.row.pk),
        quota=item.space.storage_bytes_used,
        recovery=list(DeploymentRecoveryState.objects.values()),
        restore=RestoreOperation.objects.values().get(pk=item.restore.pk),
    )


def assert_retained(item, store, before):
    assert store.objects == before.objects
    assert store.calls == before.calls and store.client_requests == before.clients
    assert RestoreRollbackObject.objects.values().get(pk=item.row.pk) == before.row
    item.space.refresh_from_db()
    assert item.space.storage_bytes_used == before.quota
    assert list(DeploymentRecoveryState.objects.values()) == before.recovery
    assert RestoreOperation.objects.values().get(pk=item.restore.pk) == before.restore


def run(entry, restore):
    if entry == "direct":
        return rollback_cleanup.cleanup_rollback_objects(restore)
    return rollback_cleanup.cleanup_expired_rollback_objects()


def assert_refused(entry, restore):
    if entry == "direct":
        with pytest.raises(RollbackCleanupOutcomeUnavailable):
            run(entry, restore)
    else:
        assert run(entry, restore) == {"status": "retained", "cleaned": 0, "skipped": 1}


def assert_host_free():
    # Acquire AND release the real flock before invoking the default owner.
    with deployment_operation_lock(blocking=False):
        assert not connection.in_atomic_block


def assert_boundaries(item):
    assert not connection.in_atomic_block
    with pytest.raises(OperationLockUnavailable), deployment_operation_lock(blocking=False):
        pytest.fail("cleanup released its host operation lock")
    for key in ((0,) if item.row.makerspace_id is None else (0, item.space.pk)):
        with advisory_lock(key) as acquired:
            assert not acquired, "cleanup released a real source boundary"


@contextmanager
def provider_boundary(item):
    """Private boundary characterization retains the same actual outer locks."""
    with ExitStack() as stack:
        stack.enter_context(deployment_operation_lock(blocking=False))
        stack.enter_context(unscoped_writer_shared_boundary())
        if item.row.makerspace_id is not None:
            stack.enter_context(boundary_tenant_write(item.space.pk))
        assert_boundaries(item)
        yield
