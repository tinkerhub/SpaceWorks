"""Real direct/expiry rollback owners retain bytes, rows and quota when fenced."""
from uuid import uuid4

import pytest
from django.db import connection
from django.utils import timezone

from apps.backup import rollback_cleanup, storage
from apps.backup.models import RestoreOperation, RestoreRollbackObject
from apps.backup.operation_lock import OperationLockUnavailable, deployment_operation_lock
from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.purge_storage import bucket_name
from apps.tenant_migration.models_source_gate import SourceMigrationGate
from tests.backup.test_restore_services import restore_fixture
from tests.makerspaces.module_cleanup_support import module_space, module_store, rollback, actor
from tests.makerspaces.purge_test_support import advisory_lock, bounded_source_wait


@pytest.fixture
def rollback_store(module_store, monkeypatch):
    # Trusted rollback deletion uses Quiet=True, still with exact version identities.
    strict = module_store.delete_objects

    def delete_objects(*, Bucket, Delete):
        assert not connection.in_atomic_block
        assert Delete["Quiet"] is True
        return strict(Bucket=Bucket, Delete={**Delete, "Quiet": False})

    monkeypatch.setattr(module_store, "delete_objects", delete_objects)
    monkeypatch.setattr(storage, "client", lambda: module_store)
    return module_store


def case(store, *, global_row=False):
    space = module_space(storage_bytes_used=100)
    _, restore = restore_fixture(stage=RestoreOperation.Stage.COMPLETED)
    row = rollback(restore, None if global_row else space, "events", "private", "legacy/source", 7)
    bucket = bucket_name("private")
    store.put(bucket, row.copy_key, b"old")
    store.put(bucket, row.copy_key, b"", marker=True)
    return space, restore, row


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["direct", "expiry"])
def test_host_busy_cleanup_keeps_every_byte_counter_and_row(entry, rollback_store):
    space, restore, row = case(rollback_store)
    before = dict(rollback_store.objects)
    with deployment_operation_lock():
        if entry == "direct":
            with pytest.raises(OperationLockUnavailable):
                rollback_cleanup.cleanup_rollback_objects(restore)
        else:
            assert rollback_cleanup.cleanup_expired_rollback_objects() == {"status": "busy", "cleaned": 0, "skipped": 0}
    assert rollback_store.calls == [] and rollback_store.objects == before
    assert RestoreRollbackObject.objects.filter(pk=row.pk).exists()
    space.refresh_from_db()
    assert space.storage_bytes_used == 100


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["direct", "expiry"])
def test_closed_known_tenant_skips_before_provider_and_settlement(entry, rollback_store):
    space, restore, row = case(rollback_store)
    now = timezone.now()
    SourceMigrationGate.objects.create(makerspace=space, state="quiesced", owner_id=uuid4(),
                                       heartbeat_at=now, lease_expires_at=now + timezone.timedelta(hours=1))
    result = (rollback_cleanup.cleanup_rollback_objects(restore) if entry == "direct"
              else rollback_cleanup.cleanup_expired_rollback_objects())
    assert result == {"status": "retained" if entry == "direct" else "checked", "cleaned": 0, "skipped": 1}
    assert rollback_store.calls == []
    assert RestoreRollbackObject.objects.filter(pk=row.pk).exists()
    space.refresh_from_db()
    assert space.storage_bytes_used == 100


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["direct", "expiry"])
@pytest.mark.parametrize("global_row", [False, True], ids=["known-maker", "unscoped-global"])
def test_actual_cleanup_callbacks_hold_host_unscoped_and_known_maker_boundaries(entry, global_row, rollback_store):
    space, restore, row = case(rollback_store, global_row=global_row)
    observations = []

    def boundary(_params):
        with pytest.raises(OperationLockUnavailable), deployment_operation_lock():
            pytest.fail("rollback owner released host lock")
        # Exclusive probes conflict with the real shared source writer boundaries.
        for key in ((0,) if global_row else (0, space.pk)):
            with advisory_lock(key) as acquired:
                assert not acquired
        assert RestoreRollbackObject.objects.filter(pk=row.pk).exists()
        assert type(space).objects.get(pk=space.pk).storage_bytes_used == 100
        observations.append(True)

    rollback_store.on_list = boundary
    result = (rollback_cleanup.cleanup_rollback_objects(restore) if entry == "direct"
              else rollback_cleanup.cleanup_expired_rollback_objects())
    assert result["cleaned"] == 1 and observations
    assert not RestoreRollbackObject.objects.filter(pk=row.pk).exists() and not rollback_store.objects
    space.refresh_from_db()
    assert space.storage_bytes_used == (100 if global_row else 93)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["direct", "expiry"])
def test_active_pending_module_intent_freezes_rollback_copy_against_independent_cleanup(entry, rollback_store):
    from django.core.exceptions import ValidationError

    space, restore, row = case(rollback_store)
    user = actor()
    rollback_store.failure = "storage"
    # Module strict deletion uses the original strict batch contract, not trusted rollback Quiet=True.
    from tests.makerspaces.module_cleanup_support import ModuleStore
    original_delete = rollback_store.delete_objects
    rollback_store.delete_objects = ModuleStore.delete_objects.__get__(rollback_store)
    with pytest.raises(ValidationError):
        purge_module(space, "events", user)
    receipt = ModulePurgeReceipt.objects.get()
    assert receipt.graph_purged_at is None and receipt.rollback_bindings[0]["id"] == row.pk
    rollback_store.delete_objects = original_delete
    rollback_store.failure = None
    rollback_store.calls.clear()
    before = dict(rollback_store.objects)
    result = (rollback_cleanup.cleanup_rollback_objects(restore) if entry == "direct"
              else rollback_cleanup.cleanup_expired_rollback_objects())
    assert result["cleaned"] == 0 and result["skipped"] == 1
    assert rollback_store.calls == [] and rollback_store.objects == before
    assert RestoreRollbackObject.objects.filter(pk=row.pk).exists()
    space.refresh_from_db()
    assert space.storage_bytes_used == 100


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("key_kind", ["unscoped", "known-maker"])
@pytest.mark.parametrize("entry", ["direct", "expiry"])
def test_real_source_contention_keeps_rollback_bytes_rows_and_quota(key_kind, entry, rollback_store, bounded_source_wait):
    from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable

    space, restore, row = case(rollback_store)
    before = dict(rollback_store.objects)
    key = 0 if key_kind == "unscoped" else space.pk
    with advisory_lock(key) as acquired:
        assert acquired
        if entry == "expiry" and key_kind == "known-maker":
            result = rollback_cleanup.cleanup_expired_rollback_objects()
            assert result["cleaned"] == 0 and result["skipped"] == 1
        else:
            with pytest.raises(SourceMigrationGateUnavailable):
                (rollback_cleanup.cleanup_rollback_objects(restore) if entry == "direct"
                 else rollback_cleanup.cleanup_expired_rollback_objects())
    assert rollback_store.calls == [] and rollback_store.objects == before
    assert RestoreRollbackObject.objects.filter(pk=row.pk).exists()
    space.refresh_from_db()
    assert space.storage_bytes_used == 100


@pytest.mark.django_db(transaction=True)
def test_global_module_receipt_never_authorizes_expiry_task_to_delete_module_bytes(rollback_store):
    from apps.backup.tasks import cleanup_expired_restore_rollbacks_task
    from tests.makerspaces.module_cleanup_support import H, module_receipt

    space = module_space()
    row = module_receipt(space, completed=True)
    identity = rollback_store.put(bucket_name("public_image"), f"staging/event/{space.pk}/{H}.png")
    before = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    assert cleanup_expired_restore_rollbacks_task() == {"status": "checked", "cleaned": 0, "skipped": 0}
    assert identity in rollback_store.objects and rollback_store.calls == []
    assert ModulePurgeReceipt.objects.values().get(pk=row.pk) == before


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["direct", "expiry"])
def test_changed_frozen_rollback_binding_refuses_independent_cleanup(entry, rollback_store):
    from django.core.exceptions import ValidationError
    from apps.backup.object_restore_versions import ObjectRestoreError
    from tests.makerspaces.module_cleanup_support import ModuleStore

    space, restore, row = case(rollback_store)
    user = actor()
    original_delete = rollback_store.delete_objects
    rollback_store.delete_objects = ModuleStore.delete_objects.__get__(rollback_store)
    rollback_store.failure = "storage"
    with pytest.raises(ValidationError):
        purge_module(space, "events", user)
    rollback_store.delete_objects = original_delete
    rollback_store.failure = None
    RestoreRollbackObject.objects.filter(pk=row.pk).update(size_bytes=row.size_bytes + 1)
    rollback_store.calls.clear()
    before = dict(rollback_store.objects)
    if entry == "direct":
        with pytest.raises(ObjectRestoreError, match="binding changed"):
            rollback_cleanup.cleanup_rollback_objects(restore)
    else:
        result = rollback_cleanup.cleanup_expired_rollback_objects()
        assert result["cleaned"] == 0 and result["skipped"] == 1
    assert rollback_store.calls == [] and rollback_store.objects == before
    assert RestoreRollbackObject.objects.filter(pk=row.pk).exists()
    space.refresh_from_db()
    assert space.storage_bytes_used == 100


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["direct", "expiry"])
def test_closed_tenant_is_counted_once_while_later_healthy_tenant_cleans(entry, rollback_store):
    closed, restore, retained = case(rollback_store)
    healthy = module_space("healthy-rollback", storage_bytes_used=100)
    cleaned = rollback(restore, healthy, "events", "private", "healthy/source", 11)
    identity = rollback_store.put(bucket_name("private"), cleaned.copy_key, b"healthy")
    now = timezone.now()
    SourceMigrationGate.objects.create(makerspace=closed, state="quiesced", owner_id=uuid4(),
                                       heartbeat_at=now, lease_expires_at=now + timezone.timedelta(hours=1))
    original = {key: value for key, value in rollback_store.objects.items() if key[1] == retained.copy_key}
    result = (rollback_cleanup.cleanup_rollback_objects(restore) if entry == "direct"
              else rollback_cleanup.cleanup_expired_rollback_objects())
    assert result == {"status": "retained" if entry == "direct" else "checked", "cleaned": 1, "skipped": 1}
    assert RestoreRollbackObject.objects.filter(pk=retained.pk).exists()
    assert not RestoreRollbackObject.objects.filter(pk=cleaned.pk).exists()
    assert all(rollback_store.objects.get(key) == value for key, value in original.items())
    assert identity not in rollback_store.objects
    assert all(params.get("Prefix") != retained.copy_key for method, params in rollback_store.calls)
    closed.refresh_from_db(); healthy.refresh_from_db()
    assert closed.storage_bytes_used == 100 and healthy.storage_bytes_used == 89
