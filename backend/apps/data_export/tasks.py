from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.data_export.lifecycle import purge_expired_job, recover_expired_job
from apps.data_export.models import DataExportJob
from apps.data_export.services import run_export_job
from apps.tenant_migration.gate_runtime import fanout_tenant_write


@shared_task(bind=True, max_retries=0)
def run_data_export_task(self, job_id):
    run_export_job(job_id)


@shared_task(bind=True, max_retries=0)
def purge_expired_exports_task(self):
    now = timezone.now()
    fallback_cutoff = now - timedelta(seconds=settings.DATA_EXPORT_DEADLINE_SECONDS)
    stale_running = Q(status=DataExportJob.Status.RUNNING) & (
        Q(deadline_at__lte=now)
        | Q(deadline_at__isnull=True, started_at__lte=fallback_cutoff)
        | Q(deadline_at__isnull=True, started_at__isnull=True, created_at__lte=fallback_cutoff)
    )
    expired = list(
        DataExportJob.objects.filter(Q(expires_at__lte=now) | stale_running)
        .order_by("pk")[:100]
    )
    counts = {"deleted": 0, "skipped": 0, "recovered": 0}
    for job in expired:
        with fanout_tenant_write(
            job.makerspace_id,
            operation="expired_data_export_purge",
            counts=counts,
        ) as should_process:
            if not should_process:
                continue
            if recover_expired_job(job.pk):
                counts["recovered"] += 1
            if purge_expired_job(job.pk):
                counts["deleted"] += 1
    return counts
