from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.data_export import lifecycle, storage, tasks
from apps.data_export.errors import ExportIntegrityError
from apps.data_export.models import DataExportJob
from apps.data_export.object_lock import export_object_lock
from apps.makerspaces import limits
from tests.backup.test_not_restored_state_e7 import _component, _operation
from tests.data_export.recovery_test_helpers import (
    events, make_job, manifest, recovery_case, usage,
)
from tests.data_export.test_api import space
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


def test_purge_delete_failure_keeps_locator_and_charge_until_one_successful_retry(
    recovery_case, monkeypatch,
):
    case = recovery_case
    job = make_job(case, status=DataExportJob.Status.AVAILABLE, accounted_size_bytes=321,
                   expires_at=timezone.now() - timedelta(seconds=1))
    limits.add_storage(case.space, 321 + 37)  # Other tenant objects must remain charged.
    objects = {job.object_key: b"archive"}
    deleted, freed = [], []
    outcomes = iter((False, True))
    real_free = limits.free_storage

    def delete(key):
        assert not connection.in_atomic_block
        deleted.append(key)
        result = next(outcomes)
        if result:
            objects.pop(key)
        return result

    def free(makerspace, size):
        freed.append((makerspace.pk, size))
        return real_free(makerspace, size)

    monkeypatch.setattr(storage, "delete_object", delete)
    monkeypatch.setattr(limits, "free_storage", free)
    before = DataExportJob.objects.filter(pk=job.pk).values().get()

    assert tasks.purge_expired_exports_task.run() == {"deleted": 0, "skipped": 0, "recovered": 0}
    assert DataExportJob.objects.filter(pk=job.pk).values().get() == before
    assert usage(case) == 358
    assert objects == {job.object_key: b"archive"}
    assert freed == []

    assert tasks.purge_expired_exports_task.run() == {"deleted": 1, "skipped": 0, "recovered": 0}
    assert not DataExportJob.objects.filter(pk=job.pk).exists()
    assert usage(case) == 37
    assert objects == {}
    # Transactional tests run on_commit callbacks for real. A duplicate post_delete
    # release would cause an extra delete or credit the unrelated 37 bytes.
    assert deleted == [job.object_key, job.object_key]
    assert freed == [(case.space.pk, 321)]
    assert tasks.purge_expired_exports_task.run() == {"deleted": 0, "skipped": 0, "recovered": 0}
    assert not lifecycle.purge_expired_job(job.pk)
    assert deleted == [job.object_key, job.object_key]
    assert freed == [(case.space.pk, 321)]
    assert usage(case) == 37


def test_held_object_lock_excludes_purge_of_completed_archive(recovery_case, monkeypatch):
    case = recovery_case
    job = make_job(case, status=DataExportJob.Status.AVAILABLE, accounted_size_bytes=31,
                   expires_at=timezone.now() - timedelta(seconds=1))
    limits.add_storage(case.space, 31)
    deleted = []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key) or True)

    with export_object_lock(job.object_key) as acquired:
        assert acquired
        with export_object_lock(job.object_key, blocking=False) as contender:
            assert not contender
        assert not lifecycle.purge_expired_job(job.pk)
        assert DataExportJob.objects.filter(pk=job.pk).exists()
        assert usage(case) == 31
        assert deleted == []

    assert lifecycle.purge_expired_job(job.pk)
    assert usage(case) == 0
    assert deleted == [job.object_key]


@pytest.mark.parametrize("fidelity", ("REDACTED", "PORTABLE"))
def test_expired_inflight_upload_is_fenced_but_bytes_wait_for_uploader_exit(
    recovery_case, monkeypatch, tmp_path, fidelity,
):
    case = recovery_case
    job = make_job(case, fidelity=fidelity)
    worker_snapshot = lifecycle._claim_job(job.pk)
    path = tmp_path / "upload.zip"
    path.write_bytes(b"in-flight archive")
    objects, deleted, uploads = {}, [], []

    def delete(key):
        assert not connection.in_atomic_block
        deleted.append(key)
        objects.pop(key, None)
        return True

    def upload(key, file_path, content_type):
        assert not connection.in_atomic_block
        uploads.append(key)
        objects[key] = file_path.read_bytes()
        DataExportJob.objects.filter(pk=job.pk).update(
            deadline_at=timezone.now() - timedelta(seconds=1),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        # Expired state is retired immediately; only byte cleanup waits for the
        # uploader's lock. This releases the failed-job cap without deleting data
        # out from under a still-open upload.
        assert lifecycle.recover_expired_job(job.pk)
        assert not lifecycle.purge_expired_job(job.pk)
        job.refresh_from_db()
        assert job.status == DataExportJob.Status.FAILED
        assert events(job, "data_export.failed").count() == 1
        assert limits._data_exports(case.space) == 0
        assert deleted == []
        assert objects[key] == b"in-flight archive"

    monkeypatch.setattr(storage, "delete_object", delete)
    monkeypatch.setattr(storage, "_upload_archive_bytes", upload)

    storage.upload_archive(job.object_key, path)

    assert objects == {job.object_key: b"in-flight archive"}
    assert deleted == []
    assert not lifecycle.recover_expired_job(job.pk)
    job.refresh_from_db()
    assert job.status == DataExportJob.Status.FAILED
    assert job.failure_code == DataExportJob.FailureCode.DEADLINE_EXCEEDED
    assert events(job, "data_export.failed").count() == 1
    with pytest.raises(ExportIntegrityError):
        lifecycle._finalize_job(worker_snapshot.pk, manifest(), 17)
    assert usage(case) == 0
    assert objects == {job.object_key: b"in-flight archive"}
    assert lifecycle.purge_expired_job(job.pk)
    assert objects == {}
    assert deleted == [job.object_key]
    with pytest.raises(ExportIntegrityError):
        storage.upload_archive(job.object_key, path)
    assert uploads == [job.object_key]
    assert objects == {}


def test_retention_sweep_does_not_delete_a_genuinely_live_worker_archive(
    recovery_case, monkeypatch,
):
    job = make_job(
        recovery_case, status=DataExportJob.Status.RUNNING,
        deadline_at=timezone.now() + timedelta(hours=1),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    before = DataExportJob.objects.filter(pk=job.pk).values().get()
    deleted = []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key) or True)

    with export_object_lock(job.object_key):
        assert tasks.purge_expired_exports_task.run() == {"deleted": 0, "skipped": 0, "recovered": 0}
    assert tasks.purge_expired_exports_task.run() == {"deleted": 0, "skipped": 0, "recovered": 0}

    assert DataExportJob.objects.filter(pk=job.pk).values().get() == before
    assert deleted == []
    assert not events(job, "data_export.failed").exists()


@pytest.mark.parametrize("boundary", ("frozen", "not-restored"))
def test_existing_fanout_skips_unwritable_tenant_and_continues_other_tenants(
    recovery_case, monkeypatch, boundary,
):
    case = recovery_case
    now = timezone.now()
    protected = make_job(
        case, status=DataExportJob.Status.RUNNING,
        deadline_at=now - timedelta(seconds=1), expires_at=now - timedelta(seconds=1),
    )
    ordinary = space(f"ordinary-{protected.pk.hex}")
    eligible = make_job(
        case, makerspace=ordinary, status=DataExportJob.Status.RUNNING,
        deadline_at=now - timedelta(seconds=1), expires_at=now - timedelta(seconds=1),
    )
    if boundary == "frozen":
        close_gate(case.space, case.actor)
    else:
        _component(_operation(makerspace_id=case.space.pk), case.space.pk)
    protected_before = DataExportJob.objects.filter(pk=protected.pk).values().get()
    deleted = []

    def delete(key):
        assert not connection.in_atomic_block
        deleted.append(key)
        return True

    monkeypatch.setattr(storage, "delete_object", delete)

    assert tasks.purge_expired_exports_task.run() == {"deleted": 1, "skipped": 1, "recovered": 1}

    assert DataExportJob.objects.filter(pk=protected.pk).values().get() == protected_before
    assert not DataExportJob.objects.filter(pk=eligible.pk).exists()
    assert protected.object_key not in deleted
    assert set(deleted) == {eligible.object_key}
    assert events(protected, "data_export.failed").count() == 0
    assert events(eligible, "data_export.failed").count() == 1
