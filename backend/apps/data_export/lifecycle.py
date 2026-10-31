"""Fenced state changes and retryable cleanup for export workers and sweepers.

Callers supply the tenant/source boundary. Only short state/accounting changes use
row locks; object I/O uses a separate lock-only connection shared with upload.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.makerspaces import limits

from . import storage
from .errors import ExportIntegrityError
from .models import DataExportJob
from .object_lock import export_object_lock
from .runner import ExportDeadlineExceeded
from .source_boundary import gated_job
from apps.tenant_migration.gate_runtime import assert_write_allowed


def job_deadline(job):
    return job.deadline_at or (job.started_at or job.created_at) + timedelta(
        seconds=settings.DATA_EXPORT_DEADLINE_SECONDS
    )


def require_running(job):
    if job is None or job.status != DataExportJob.Status.RUNNING:
        raise ExportIntegrityError("The claimed export is no longer running.")
    if job_deadline(job) <= timezone.now():
        raise ExportDeadlineExceeded("finalize", 0)


@gated_job
def _claim_job(job_id):
    # Redelivery retires an abandoned claim, but never starts a second producer.
    recover_expired_job(job_id)
    with transaction.atomic():
        job = _locked_job(job_id)
        if job is None or job.status != DataExportJob.Status.PENDING:
            return None
        now = timezone.now()
        if job.expires_at <= now:
            _mark_failed_locked(job, DataExportJob.FailureCode.DEADLINE_EXCEEDED,
                                "The export expired before it could start.")
            return None
        job.status = DataExportJob.Status.RUNNING
        job.started_at = now
        job.deadline_at = now + timedelta(seconds=settings.DATA_EXPORT_DEADLINE_SECONDS)
        job.failure_code = ""
        job.failure_detail = ""
        job.save(update_fields=(
            "status", "started_at", "deadline_at", "failure_code",
            "failure_detail", "updated_at",
        ))
        return job


@gated_job
def _finalize_job(job_id, manifest, size):
    # No compensating deletion here: the caller may have lost its state fence to
    # recovery or another completed delivery. Only _fail_job can clean FAILED rows.
    with transaction.atomic():
        job = _locked_job(job_id)
        require_running(job)
        limits.add_storage(job.makerspace, size)
        require_running(job)  # Quota locking may itself have waited past the deadline.
        job.status = DataExportJob.Status.AVAILABLE
        job.accounted_size_bytes = size
        job.manifest = manifest
        job.snapshot_at = manifest["snapshot_at"]
        job.completed_at = timezone.now()
        job.save(update_fields=(
            "status", "accounted_size_bytes", "manifest", "snapshot_at",
            "completed_at", "updated_at",
        ))
        audit.record(
            job.requested_by, "data_export.completed", makerspace=job.makerspace,
            target=job, meta={
                "fidelity": job.fidelity,
                "row_counts": manifest["row_counts"],
                "total_rows": manifest["total_rows"],
            },
        )


@gated_job
def _fail_job(job, code, detail, manifest=None):
    # Portable dispatch uses the historical failure entry point with a PENDING
    # snapshot. It may retire only that unclaimed job, never a worker that won.
    if job.status == DataExportJob.Status.PENDING:
        return fail_dispatch(job)
    with export_object_lock(job.object_key):
        with transaction.atomic():
            locked = _locked_job(job.pk)
            if locked is None or locked.status not in {
                DataExportJob.Status.RUNNING, DataExportJob.Status.FAILED,
            }:
                return False
            if locked.status == DataExportJob.Status.RUNNING:
                if job_deadline(locked) <= timezone.now():
                    code = DataExportJob.FailureCode.DEADLINE_EXCEEDED
                _mark_failed_locked(locked, code, detail, manifest)
        # A late failure never deletes AVAILABLE bytes or rewrites a prior failure.
        return storage.delete_object(locked.object_key)


@gated_job
def fail_dispatch(job):
    """An ambiguous publish error may retire only an unclaimed PENDING job."""
    with transaction.atomic():
        locked = _locked_job(job.pk)
        if locked is None or locked.status != DataExportJob.Status.PENDING:
            return False
        _mark_failed_locked(
            locked, DataExportJob.FailureCode.INTERNAL_ERROR,
            "The export could not be queued. Please request a new export.",
        )
        return True


@gated_job
def recover_expired_job(job_id):
    with transaction.atomic():
        locked = _locked_job(job_id)
        if (locked is None or locked.status != DataExportJob.Status.RUNNING
                or job_deadline(locked) > timezone.now()):
            return False
        _mark_failed_locked(
            locked, DataExportJob.FailureCode.DEADLINE_EXCEEDED,
            "The export worker did not finish before its deadline.",
        )
    # Retire the state even if an upload is still in flight, but keep the row and
    # locator until that upload exits. It cannot finalize or start another upload.
    with export_object_lock(locked.object_key, blocking=False) as acquired:
        if acquired:
            storage.delete_object(locked.object_key)
    return True


@gated_job
def purge_expired_job(job_id):
    job = DataExportJob.objects.filter(pk=job_id).first()
    if job is None:
        return False
    with export_object_lock(job.object_key, blocking=False) as acquired:
        if not acquired:
            return False
        with transaction.atomic():
            locked = _locked_job(job_id)
            if locked is None or locked.expires_at > timezone.now():
                return False
            if locked.status == DataExportJob.Status.RUNNING:
                # Recovery must fence the worker before any deletion is allowed.
                return False
            if locked.status == DataExportJob.Status.PENDING:
                _mark_failed_locked(
                    locked, DataExportJob.FailureCode.DEADLINE_EXCEEDED,
                    "The export expired before it could start.",
                )
        if not storage.delete_object(locked.object_key):
            # Preserve the locator AND charged size as the next sweep's journal.
            return False
        with transaction.atomic():
            locked = _locked_job(job_id)
            if locked is None:
                return False
            limits.free_storage(locked.makerspace, locked.accounted_size_bytes)
            locked._archive_released = True
            locked.delete()
        return True


def _locked_job(job_id):
    return (
        DataExportJob.objects.select_for_update(of=("self",))
        .select_related("makerspace", "requested_by")
        .filter(pk=job_id).first()
    )


def _mark_failed_locked(job, code, detail, manifest=None):
    assert_write_allowed(job.makerspace_id)
    job.status = DataExportJob.Status.FAILED
    job.failure_code = code
    job.failure_detail = detail[:500]
    job.manifest = manifest or {}
    if code == DataExportJob.FailureCode.DEADLINE_EXCEEDED:
        job.manifest.setdefault("deadline", {
            "outcome": "exhausted", "seconds": settings.DATA_EXPORT_DEADLINE_SECONDS,
        })
    job.completed_at = timezone.now()
    job.download_token_digest = ""
    job.download_token_expires_at = None
    job.download_token_consumed_at = None
    job.download_issued_to = None
    job.save(update_fields=(
        "status", "failure_code", "failure_detail", "manifest", "completed_at",
        "download_token_digest", "download_token_expires_at",
        "download_token_consumed_at", "download_issued_to", "updated_at",
    ))
    audit.record(
        job.requested_by, "data_export.failed", makerspace=job.makerspace,
        target=job, meta={"failure_code": code, "fidelity": job.fidelity},
    )
