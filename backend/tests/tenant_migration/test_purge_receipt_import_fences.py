"""Task exemptions are safe only while actual import work retains key-zero."""

from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.makerspaces.purge_locks import PurgeBusy, purge_boundary
from apps.makerspaces.purge_receipts import retry_cleanup
from apps.tenant_migration import import_finalization, import_job_cleanup, object_storage
from apps.tenant_migration.archive_retention import schedule_import_archive_unlink
from apps.tenant_migration.import_staging import stage_encrypted_upload
from apps.tenant_migration.materialization import materialize_tenant
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from apps.tenant_migration.services_import_job import claim_import_job, create_import_job, run_import_job
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from tests.data_export.portable_helpers import make_space, make_user
from tests.encryption.conftest import enabled_encryption
from tests.makerspaces.purge_test_support import (
    actor, advisory_lock, bounded_source_wait, purge_store, receipt,
)
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.tenant_migration.object_helpers import (
    encryption_key, memory_objects, prepare_source_objects,
    remove_source_object_footprint, write_object_bundle,
)
from tests.tenant_migration.test_import_jobs import make_job

pytestmark = pytest.mark.django_db(transaction=True)


def observe_boundary(user, row, events, phase):
    assert not connection.in_atomic_block, f"{phase} held an application transaction over remote I/O"
    with advisory_lock(0) as acquired:
        assert not acquired, f"{phase} lacked actual unscoped publication exclusion"
    with pytest.raises(PurgeBusy):
        retry_cleanup(row.pk, user)
    events.append(phase)


@pytest.mark.parametrize("failure", [False, True], ids=["publish-readback", "failure-cleanup"])
def test_materialization_owns_fence_through_staging_publish_readback_and_failure(
    failure, memory_objects, purge_store, monkeypatch,
):
    user, row, events = actor(), receipt(), []
    for name in ("upload_staged", "copy_from_staging", "digest_object", "delete_object"):
        original = getattr(object_storage, name)

        def observed(*args, _name=name, _original=original, **kwargs):
            observe_boundary(user, row, events, _name)
            result = _original(*args, **kwargs)
            if failure and _name == "copy_from_staging":
                raise RuntimeError("promotion failed after writing bytes")
            return result

        monkeypatch.setattr(object_storage, name, observed)
    with enabled_encryption():
        source_user = make_user("receipt-fenced-import")
        source = make_space("receipt-fenced-import")
        with portable_import_case(source, source_user, prepare_source=prepare_source_objects) as case:
            case.decide_walk_in(source_user)
            write_object_bundle(case.root)
            remove_source_object_footprint(case, memory_objects)
            if failure:
                with pytest.raises(RuntimeError, match="promotion failed"):
                    materialize_tenant(case.root, case.job, case.carried)
                assert "delete_object" in events
                assert set(case.job.import_objects.values_list("state", flat=True)) == {TenantImportObject.State.ROLLED_BACK}
            else:
                result = materialize_tenant(case.root, case.job, case.carried)
                assert result.objects_promoted == 2
                assert set(case.job.import_objects.values_list("state", flat=True)) == {TenantImportObject.State.VERIFIED}
    assert {"upload_staged", "copy_from_staging", "digest_object"} <= set(events)
    assert not purge_store.deletes
    with advisory_lock(0) as acquired:
        assert acquired  # Failure and success release the fence.


@pytest.mark.parametrize("entry", ["claim", "execute", "finalize", "stage", "cleanup_jobs", "cleanup_objects", "recover"])
def test_receipt_exclusive_blocks_import_entry_before_claim_or_staging(
    entry, bounded_source_wait, purge_store, tmp_path,
):
    user, row = actor(), receipt()
    job = make_job(status=TenantImportJob.Status.READY)
    before = TenantImportJob.objects.values().get(pk=job.pk)
    upload = Mock()
    calls = {
        "claim": lambda: claim_import_job(actor=user, job=job),
        "execute": lambda: run_import_job(job.pk, actor_id=user.pk),
        "finalize": lambda: import_finalization.finalize_import_job(job, actor=user),
        "stage": lambda: stage_encrypted_upload(upload),
        "cleanup_jobs": lambda: import_job_cleanup.cleanup_expired_import_jobs(),
        "cleanup_objects": lambda: import_job_cleanup.cleanup_abandoned_import_objects(),
        "recover": lambda: import_job_cleanup.resume_expired_finalizing_import_jobs(),
    }
    with purge_boundary(row.source_makerspace_id, all_tenants=True):
        with pytest.raises(SourceMigrationGateUnavailable):
            calls[entry]()
    upload.chunks.assert_not_called()
    assert TenantImportJob.objects.values().get(pk=job.pk) == before
    assert not list(tmp_path.rglob("*.tar.age"))


def test_execution_failure_and_rollback_are_inside_same_fence(purge_store, monkeypatch):
    user, row, events = actor(), receipt(), []
    job = make_job(status=TenantImportJob.Status.MATERIALIZING)
    monkeypatch.setattr("apps.tenant_migration.import_staging.decrypted_archive", lambda _path: nullcontext((None, ())))

    def fail(*args, **kwargs):
        observe_boundary(user, row, events, "materialize")
        raise RuntimeError("materialization refused")

    def cleanup(locked):
        observe_boundary(user, row, events, "rollback")
        assert locked.status == TenantImportJob.Status.FAILED

    monkeypatch.setattr("apps.tenant_migration.materialization.materialize_tenant", fail)
    monkeypatch.setattr("apps.tenant_migration.object_import.rollback_import_objects", cleanup)
    with pytest.raises(RuntimeError, match="materialization refused"):
        run_import_job(job.pk, actor_id=user.pk)
    assert events == ["materialize", "rollback"]
    job.refresh_from_db()
    assert job.status == TenantImportJob.Status.FAILED


def test_recovery_dispatch_and_deferred_unlink_execute_inside_unscoped_boundary(
    purge_store, monkeypatch, tmp_path,
):
    user, row, events = actor(), receipt(), []
    job = make_job(actor=user, status=TenantImportJob.Status.FINALIZING)

    def dispatch(job_id, actor_id):
        observe_boundary(user, row, events, "recovery-dispatch")
        assert (job_id, actor_id) == (str(job.pk), user.pk)

    monkeypatch.setattr("apps.tenant_migration.tasks.run_import_job_task.delay", dispatch)
    assert import_job_cleanup.resume_expired_finalizing_import_jobs() == 1
    path = tmp_path / "archive.age"
    path.write_bytes(b"encrypted archive")
    unlink = Path.unlink

    def observed_unlink(target, *args, **kwargs):
        observe_boundary(user, row, events, "deferred-unlink")
        return unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", observed_unlink)
    with transaction.atomic():
        schedule_import_archive_unlink(str(path), job.pk)
        assert path.exists()
    assert not path.exists()
    assert events == ["recovery-dispatch", "deferred-unlink"]


def test_retention_cleanup_claim_and_remote_rollback_are_fenced(purge_store, monkeypatch):
    user, row, events = actor(), receipt(), []
    job = make_job(expires_at=timezone.now() - timedelta(seconds=1))
    claim = import_job_cleanup._claim_named_cleanup_lease

    def observed_claim(*args, **kwargs):
        observe_boundary(user, row, events, "cleanup-claim")
        return claim(*args, **kwargs)

    def rollback(locked):
        observe_boundary(user, row, events, "cleanup-rollback")
        assert locked.pk == job.pk

    monkeypatch.setattr(import_job_cleanup, "_claim_named_cleanup_lease", observed_claim)
    monkeypatch.setattr("apps.tenant_migration.object_import.rollback_import_objects", rollback)
    assert import_job_cleanup.cleanup_expired_import_jobs() == 1
    assert not TenantImportJob.objects.filter(pk=job.pk).exists()
    assert events == ["cleanup-claim", "cleanup-rollback"]


def test_upload_staging_and_create_failure_unlink_keep_real_fence(purge_store, monkeypatch):
    user, row, events = actor(), receipt(), []

    class Upload:
        def chunks(self):
            observe_boundary(user, row, events, "encrypted-staging")
            yield b"encrypted archive with deliberately wrong digest"

    unlink = Path.unlink

    def observed_unlink(path, *args, **kwargs):
        observe_boundary(user, row, events, "create-failure-unlink")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", observed_unlink)
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError, match="digest does not match"):
        create_import_job(actor=user, archive=Upload(), source_archive_digest="0" * 64,
                          expires_at=timezone.now() + timedelta(days=1))
    assert not TenantImportJob.objects.exists()
    assert events == ["encrypted-staging", "create-failure-unlink"]


def test_deferred_unlink_waits_for_receipt_exclusive_at_execution_time(
    purge_store, bounded_source_wait, monkeypatch, tmp_path,
):
    row = receipt()
    job = make_job()
    path = tmp_path / "still-retained.age"
    path.write_bytes(b"encrypted archive")
    pending = []
    monkeypatch.setattr(transaction, "on_commit", pending.append)
    schedule_import_archive_unlink(str(path), job.pk)
    assert len(pending) == 1 and path.exists()
    with purge_boundary(row.source_makerspace_id, all_tenants=True):
        with pytest.raises(SourceMigrationGateUnavailable):
            pending[0]()
    assert path.exists()
    pending[0]()
    assert not path.exists()
