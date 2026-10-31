from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.data_export import lifecycle, services, storage, tasks
from apps.data_export.errors import ExportIntegrityError
from apps.data_export.models import DataExportJob
from apps.data_export.runner import ExportDeadlineExceeded
from apps.tenant_migration import services_export_job
from tests.data_export.recovery_test_helpers import (
    events, make_job, manifest, recovery_case, usage,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("fidelity", ("REDACTED", "PORTABLE"))
@pytest.mark.parametrize("clock", ("deadline", "started", "created"))
def test_redelivery_retires_expired_claim_once_without_restarting_producer(
    recovery_case, monkeypatch, settings, fidelity, clock,
):
    settings.DATA_EXPORT_DEADLINE_SECONDS = 60
    now = timezone.now()
    job = make_job(
        recovery_case, fidelity=fidelity, status=DataExportJob.Status.RUNNING,
        deadline_at=now - timedelta(seconds=1) if clock == "deadline" else None,
        started_at=now - timedelta(minutes=2) if clock == "started" else None,
        download_token_digest="a" * 64,
        download_token_expires_at=now + timedelta(hours=1),
        download_issued_to=recovery_case.actor,
    )
    DataExportJob.objects.filter(pk=job.pk).update(created_at=now - timedelta(hours=1))
    produced, deleted = [], []
    monkeypatch.setattr(services, "build_archive", lambda job: produced.append(job.pk))
    monkeypatch.setattr(services_export_job, "build_tenant_migration_archive",
                        lambda *args, **kwargs: produced.append("portable"))
    run = (services_export_job.run_migration_export_job if fidelity == "PORTABLE"
           else services.run_export_job)

    def delete(key):
        assert not connection.in_atomic_block
        deleted.append(key)
        return True

    monkeypatch.setattr(storage, "delete_object", delete)

    assert run(job.pk) is None
    terminal = DataExportJob.objects.filter(pk=job.pk).values().get()
    assert run(job.pk) is None

    job.refresh_from_db()
    assert job.status == DataExportJob.Status.FAILED
    assert job.failure_code == DataExportJob.FailureCode.DEADLINE_EXCEEDED
    assert job.manifest["deadline"] == {"outcome": "exhausted", "seconds": 60}
    assert job.completed_at is not None
    assert job.download_token_digest == ""
    assert job.download_token_expires_at is None
    assert job.download_issued_to_id is None
    assert job.accounted_size_bytes == usage(recovery_case) == 0
    assert events(job, "data_export.failed").count() == 1
    assert DataExportJob.objects.filter(pk=job.pk).values().get() == terminal
    assert produced == []
    assert deleted == [job.object_key]


@pytest.mark.parametrize("explicit_deadline", (False, True))
def test_live_running_redelivery_preserves_claim_even_with_old_creation_time(
    recovery_case, monkeypatch, settings, explicit_deadline,
):
    settings.DATA_EXPORT_DEADLINE_SECONDS = 3600
    now = timezone.now()
    job = make_job(
        recovery_case, status=DataExportJob.Status.RUNNING,
        started_at=now - timedelta(days=1) if explicit_deadline else now,
        deadline_at=now + timedelta(hours=1) if explicit_deadline else None,
    )
    DataExportJob.objects.filter(pk=job.pk).update(created_at=now - timedelta(days=1))
    before = DataExportJob.objects.filter(pk=job.pk).values().get()
    calls = []
    monkeypatch.setattr(services, "build_archive", lambda job: calls.append("producer"))
    monkeypatch.setattr(storage, "delete_object", lambda key: calls.append("delete") or True)

    assert services.run_export_job(job.pk) is None

    assert DataExportJob.objects.filter(pk=job.pk).values().get() == before
    assert calls == []
    assert not events(job, "data_export.failed").exists()


@pytest.mark.parametrize("clock", ("deadline", "started", "created"))
def test_existing_purge_task_recovers_stale_claim_before_retention_expires(
    recovery_case, monkeypatch, settings, clock,
):
    settings.DATA_EXPORT_DEADLINE_SECONDS = 60
    now = timezone.now()
    job = make_job(
        recovery_case, status=DataExportJob.Status.RUNNING,
        deadline_at=now - timedelta(seconds=1) if clock == "deadline" else None,
        started_at=now - timedelta(minutes=2) if clock == "started" else None,
    )
    DataExportJob.objects.filter(pk=job.pk).update(created_at=now - timedelta(hours=1))
    deleted = []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key) or True)

    assert tasks.purge_expired_exports_task.run() == {"deleted": 0, "skipped": 0, "recovered": 1}
    assert tasks.purge_expired_exports_task.run() == {"deleted": 0, "skipped": 0, "recovered": 0}

    job.refresh_from_db()
    assert job.status == DataExportJob.Status.FAILED
    assert job.expires_at > timezone.now()
    assert job.failure_code == DataExportJob.FailureCode.DEADLINE_EXCEEDED
    assert events(job, "data_export.failed").count() == 1
    assert deleted == [job.object_key]


@pytest.mark.parametrize("terminal_state", ("available", "failed"))
def test_late_finalize_and_failure_preserve_terminal_outcome_and_completed_bytes(
    recovery_case, monkeypatch, terminal_state,
):
    case = recovery_case
    job = make_job(case)
    worker_snapshot = lifecycle._claim_job(job.pk)
    objects = {job.object_key: b"completed"}
    deleted = []

    def delete(key):
        assert not connection.in_atomic_block
        deleted.append(key)
        objects.pop(key, None)
        return True

    monkeypatch.setattr(storage, "delete_object", delete)
    if terminal_state == "available":
        lifecycle._finalize_job(job.pk, manifest(), 9)
    else:
        lifecycle._fail_job(worker_snapshot, DataExportJob.FailureCode.STORAGE_ERROR,
                            "Original terminal failure", {"original": True})
    before = DataExportJob.objects.filter(pk=job.pk).values().get()
    before_usage = usage(case)
    before_failed = events(job, "data_export.failed").count()

    with pytest.raises(ExportIntegrityError):
        lifecycle._finalize_job(job.pk, manifest(), 777)
    lifecycle._fail_job(worker_snapshot, DataExportJob.FailureCode.INTERNAL_ERROR,
                        "Late different failure", {"late": True})

    assert DataExportJob.objects.filter(pk=job.pk).values().get() == before
    assert usage(case) == before_usage == (9 if terminal_state == "available" else 0)
    assert events(job, "data_export.failed").count() == before_failed
    assert events(job, "data_export.completed").count() == int(terminal_state == "available")
    if terminal_state == "available":
        assert objects == {job.object_key: b"completed"}
        assert deleted == []


@pytest.mark.parametrize("fidelity", ("REDACTED", "PORTABLE"))
@pytest.mark.parametrize("recovered", (False, True), ids=("expired", "recovered"))
def test_shared_upload_boundary_refuses_expired_or_recovered_runner(
    recovery_case, monkeypatch, tmp_path, fidelity, recovered,
):
    job = make_job(
        recovery_case, fidelity=fidelity, status=DataExportJob.Status.RUNNING,
        deadline_at=timezone.now() - timedelta(seconds=1),
    )
    deleted, uploaded = [], []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key) or True)
    monkeypatch.setattr(storage, "_upload_archive_bytes", lambda *args: uploaded.append(args))
    if recovered:
        assert lifecycle.recover_expired_job(job.pk)
    path = tmp_path / "late.zip"
    path.write_bytes(b"must never reappear")

    expected_error = ExportIntegrityError if recovered else ExportDeadlineExceeded
    with pytest.raises(expected_error):
        storage.upload_archive(job.object_key, path)

    assert uploaded == []
    assert deleted == ([job.object_key] if recovered else [])
    assert usage(recovery_case) == 0


@pytest.mark.parametrize("operation", ("dispatch", "recovery", "finalize"))
def test_lifecycle_audit_failure_rolls_back_state_tokens_and_storage_charge(
    recovery_case, monkeypatch, operation,
):
    job = make_job(recovery_case)
    if operation != "dispatch":
        lifecycle._claim_job(job.pk)
    if operation == "recovery":
        DataExportJob.objects.filter(pk=job.pk).update(
            deadline_at=timezone.now() - timedelta(seconds=1),
        )
    DataExportJob.objects.filter(pk=job.pk).update(
        download_token_digest="b" * 64, download_issued_to=recovery_case.actor,
        download_token_expires_at=timezone.now() + timedelta(hours=1),
    )
    before = DataExportJob.objects.filter(pk=job.pk).values().get()
    deleted = []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key) or True)

    def audit_unavailable(*args, **kwargs):
        raise RuntimeError("injected audit outage")

    monkeypatch.setattr(lifecycle.audit, "record", audit_unavailable)
    with pytest.raises(RuntimeError, match="audit outage"):
        if operation == "dispatch":
            lifecycle.fail_dispatch(job)
        elif operation == "recovery":
            lifecycle.recover_expired_job(job.pk)
        else:
            lifecycle._finalize_job(job.pk, manifest(), 100)

    assert DataExportJob.objects.filter(pk=job.pk).values().get() == before
    assert usage(recovery_case) == 0
    assert not events(job, "data_export.failed").exists()
    assert not events(job, "data_export.completed").exists()
    assert deleted == []
