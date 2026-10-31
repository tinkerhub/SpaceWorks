"""Real publisher/source/host exclusion and persistent capture/counter fences."""
from io import StringIO
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup import archive_payload
from apps.backup.operation_lock import OperationLockUnavailable, deployment_operation_lock
from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_intent import PurgeInProgress, assert_capture_allowed
from apps.makerspaces.purge_locks import PurgeBusy
from apps.tenant_migration import preflight, source_gate, tenant_dump_capture
from apps.tenant_migration.models_source_gate import SourceMigrationGate
from tests.makerspaces.module_cleanup_support import (
    actor, module_receipt, module_space, module_store, purged_event_case,
)
from tests.makerspaces.purge_test_support import advisory_lock


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["initial", "retry"])
@pytest.mark.parametrize("held", ["host", "unscoped", "tenant", "other-tenant"])
def test_busy_real_exclusion_refuses_before_bytes_or_receipt_attempt(entry, held, module_store):
    space, user = module_space(), actor()
    other = module_space("other-writer")
    row = module_receipt(space, completed=True) if entry == "retry" else None
    before = list(AuditLog.objects.values_list("pk", flat=True))
    boundary = deployment_operation_lock() if held == "host" else advisory_lock(
        {"unscoped": 0, "tenant": space.pk, "other-tenant": other.pk}[held], shared=True,
    )
    with boundary as owned:
        assert owned
        with pytest.raises(OperationLockUnavailable if held == "host" else PurgeBusy):
            retry_cleanup(row.pk, user) if row else purge_module(space, "events", user)
    assert module_store.calls == []
    assert list(AuditLog.objects.values_list("pk", flat=True)) == before
    if row:
        row.refresh_from_db()
        assert row.last_attempt_at == row.intent_created_at
    else:
        assert not ModulePurgeReceipt.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_provider_callbacks_observe_exclusive_host_and_every_tenant_source_lock(module_store):
    space, user, _event, _key = purged_event_case(module_store)
    other = module_space("other-current-publisher")
    observations = []

    def prove_exclusion(_params):
        with pytest.raises(OperationLockUnavailable), deployment_operation_lock():
            pytest.fail("host lock released during listing/readback")
        for key in (0, space.pk, other.pk):
            with advisory_lock(key, shared=True) as acquired:
                assert not acquired, "a current publisher can race cleanup"
        observations.append(True)

    module_store.on_list = prove_exclusion
    purge_module(space, "events", user)
    assert len(observations) > 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("state", ["draining", "quiesced", "migrated_out"])
def test_closed_source_refuses_module_initial_and_retry_before_io(state, module_store):
    space, user = module_space(), actor()
    row = module_receipt(space, completed=True)
    now = timezone.now()
    SourceMigrationGate.objects.create(makerspace=space, state=state, owner_id=uuid4(),
                                       heartbeat_at=now, lease_expires_at=now + timezone.timedelta(hours=1))
    with pytest.raises(ValidationError):
        purge_module(space, "events", user)
    with pytest.raises(ValidationError):
        retry_cleanup(row.pk, user)
    assert module_store.calls == []


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["tenant-payload", "source-preflight", "source-claim", "dump-request"])
def test_pending_intent_blocks_actual_capture_entries_before_payload_object_or_capture_row(entry, module_store, tmp_path, monkeypatch):
    space, user = module_space(), actor()
    module_receipt(space)
    raw = Mock(side_effect=AssertionError("raw DB rows captured"))
    objects = Mock(side_effect=AssertionError("object capture reached"))
    monkeypatch.setattr(archive_payload, "raw_records", raw)
    monkeypatch.setattr(tenant_dump_capture, "capture_database_image", raw)
    monkeypatch.setattr(tenant_dump_capture, "capture_tenant_objects", objects)
    from apps.tenant_migration.models import TenantDumpCapture
    with pytest.raises(PurgeInProgress):
        if entry == "tenant-payload":
            archive_payload._tenant_payload(space.pk, tmp_path / "forbidden")
        elif entry == "source-preflight":
            preflight.run_source_preflight(space)
        elif entry == "source-claim":
            source_gate.claim(space, user)
        else:
            tenant_dump_capture.request_tenant_dump_capture(user, space)
    assert not TenantDumpCapture.objects.exists()
    assert not SourceMigrationGate.objects.exists()
    raw.assert_not_called(); objects.assert_not_called()
    assert not (tmp_path / "forbidden").exists() and module_store.calls == []


@pytest.mark.django_db
def test_pending_capture_scope_is_exact_and_completed_receipts_allow_capture():
    space, other = module_space(), module_space("capture-other")
    row = module_receipt(space)
    assert_capture_allowed([other.pk])
    for scope in (None, [space.pk]):
        with pytest.raises(PurgeInProgress):
            assert_capture_allowed(scope)
    now = timezone.now()
    row.graph_purged_at = row.last_attempt_at = row.last_verified_at = now
    row.save(update_fields=["graph_purged_at", "last_attempt_at", "last_verified_at"])
    assert_capture_allowed([space.pk])
    assert_capture_allowed()


@pytest.mark.django_db(transaction=True)
def test_recompute_pending_intent_refuses_before_head_or_counter_write(module_store, monkeypatch):
    from apps.makerspaces.management.commands import recompute_storage
    from apps.tenant_migration.gate_runtime import boundary_tenant_write

    space = module_space(storage_bytes_used=321)
    module_receipt(space)
    head = Mock(side_effect=AssertionError("HEAD during pending module intent"))
    monkeypatch.setattr(recompute_storage.public_image_storage, "object_size", head)
    command = recompute_storage.Command(stdout=StringIO())
    with boundary_tenant_write(space.pk, exclusive=True), pytest.raises(ValidationError, match="unfinished"):
        command._recompute(space)
    command.handle(makerspace=space.slug)
    head.assert_not_called()
    space.refresh_from_db()
    assert space.storage_bytes_used == 321 and "module purge pending" in command.stdout.getvalue()


@pytest.mark.django_db(transaction=True)
def test_lost_real_exclusive_connection_refuses_module_before_delete_or_intent(module_store, monkeypatch):
    from apps.makerspaces import purge_locks
    from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable

    space, user, _event, _key = purged_event_case(module_store)
    opened = []
    original = purge_locks._new_lock_connection

    def actual_connection():
        db = original()
        opened.append(db)
        return db

    monkeypatch.setattr(purge_locks, "_new_lock_connection", actual_connection)

    def release_actual_proof(_params):
        opened[0].rollback()
        module_store.on_list = None

    module_store.on_list = release_actual_proof
    with pytest.raises(SourceMigrationGateUnavailable):
        purge_module(space, "events", user)
    assert not module_store.deletes and not ModulePurgeReceipt.objects.exists()
    space.refresh_from_db()
    assert space.storage_bytes_used == 10000


@pytest.mark.django_db(transaction=True)
def test_synchronous_callback_suppression_rejects_impostor_and_released_real_proof(module_store):
    from apps.makerspaces.purge_cleanup import owns_cleanup, synchronous_cleanup
    from apps.makerspaces.purge_locks import purge_boundary
    from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable

    space = module_space()
    with pytest.raises(SourceMigrationGateUnavailable), synchronous_cleanup(space.pk, verify=lambda: None):
        pytest.fail("an arbitrary callable granted deletion callback ownership")
    with purge_boundary(space.pk, all_tenants=True) as verify:
        with pytest.raises(SourceMigrationGateUnavailable), synchronous_cleanup(space.pk, verify=lambda: verify()):
            pytest.fail("a wrapper forged the retained boundary identity")
        with synchronous_cleanup(space.pk, verify=verify):
            assert owns_cleanup(space.pk)
    with pytest.raises(SourceMigrationGateUnavailable), synchronous_cleanup(space.pk, verify=verify):
        pytest.fail("released proof retained callback suppression")
    assert not owns_cleanup(space.pk) and module_store.calls == []


@pytest.mark.django_db(transaction=True)
def test_pending_intent_blocks_deployment_payload_before_dump_and_object_capture(module_store, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from apps.backup.models import BackupArchive

    space = module_space()
    module_receipt(space)
    dump = Mock(side_effect=AssertionError("database dump reached"))
    objects = Mock(side_effect=AssertionError("object capture reached"))
    monkeypatch.setattr(archive_payload, "_pg_dump", dump)
    monkeypatch.setattr(archive_payload, "_capture_objects", objects)
    with pytest.raises(PurgeInProgress):
        archive_payload._snapshot_payload(SimpleNamespace(scope=BackupArchive.Scope.DEPLOYMENT), tmp_path, {}, [])
    dump.assert_not_called(); objects.assert_not_called()
    assert module_store.calls == []
