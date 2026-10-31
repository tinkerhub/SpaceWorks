"""Task execution owns publication exclusion through failure cleanup."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models_import_job import TenantImportJob
from .import_boundary import import_writer


@import_writer
def run_import_job(job_id, *, actor_id, target_identity=None):
    from apps.accounts.models import User
    from .import_finalization import finalize_import_job
    from .insertion_errors import (
        ImportCompletionAuditError,
        ImportPromotionClaimLost,
        ImportPromotionInProgress,
        MaterializationAlreadyCommitted,
    )
    from .materialization import materialize_tenant

    actor = User.objects.get(pk=actor_id)
    from .services_import_job import _require_superadmin

    _require_superadmin(actor)
    job = TenantImportJob.objects.get(pk=job_id)
    if job.status == TenantImportJob.Status.COMPLETED:
        return job
    if job.status not in {
        TenantImportJob.Status.MATERIALIZING,
        TenantImportJob.Status.FINALIZING,
    }:
        raise ValidationError({"detail": "The import has not been claimed for execution."})

    try:
        if job.status == TenantImportJob.Status.MATERIALIZING:
            from .import_staging import decrypted_archive

            try:
                with decrypted_archive(job.archive_path) as (root, carried):
                    materialize_tenant(
                        root, job, carried, target_identity=target_identity
                    )
            except MaterializationAlreadyCommitted:
                # A concurrent delivery won the database transaction. Its committed
                # FINALIZING state is the authority for the remaining work.
                pass
        job.refresh_from_db()
        job = finalize_import_job(job, actor=actor)
    except ImportPromotionClaimLost:
        # A replacement delivery owns finalization. Its status and objects are
        # authoritative, so this stale worker exits without changing either.
        return TenantImportJob.objects.get(pk=job.pk)
    except ImportPromotionInProgress:
        # A periodic, idempotently leased sweep requeues FINALIZING after this object
        # lease expires. It deliberately excludes jobs with any still-live claim.
        return TenantImportJob.objects.get(pk=job.pk)
    except ImportCompletionAuditError:
        # Completion and its audit entry share one transaction. Keep FINALIZING and
        # its verified objects intact so the scheduled sweep can retry that transaction.
        raise
    except Exception as exc:
        failure_detail = str(exc).strip()[:500] or type(exc).__name__
        failed_active = TenantImportJob.objects.filter(
            pk=job.pk,
            status__in=(
                TenantImportJob.Status.MATERIALIZING,
                TenantImportJob.Status.FINALIZING,
            ),
        ).update(
            status=TenantImportJob.Status.FAILED,
            failure_code="materialization_failed",
            failure_detail=failure_detail,
            terminal_at=timezone.now(),
        )
        if failed_active:
            from .object_import import rollback_import_objects

            rollback_job = TenantImportJob.objects.select_related(
                "target_makerspace", "actor"
            ).get(pk=job.pk)
            rollback_import_objects(rollback_job)
        else:
            # materialize_tenant() records FAILED before re-raising. Annotate only
            # that still-unexplained failure and never overwrite a competing reason.
            TenantImportJob.objects.filter(
                pk=job.pk,
                status=TenantImportJob.Status.FAILED,
                failure_code="",
                failure_detail="",
            ).update(
                failure_code="materialization_failed",
                failure_detail=failure_detail,
            )
        raise
    return job
