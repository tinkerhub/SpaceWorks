"""Post-commit, best-effort retention for staged encrypted import archives."""

import logging
from pathlib import Path

from django.db import transaction

from .import_boundary import import_writer


logger = logging.getLogger(__name__)


def schedule_import_archive_unlink(path, job_id, *, tenant_id=None):
    if not path:
        return
    from .models_import_job import TenantImportJob
    from apps.makerspaces.purge_cleanup import owns_cleanup

    if tenant_id is None:
        tenant_id = TenantImportJob.objects.filter(pk=job_id).values_list("target_makerspace_id", flat=True).first()
    if tenant_id is not None and owns_cleanup(tenant_id):
        return

    @import_writer
    def unlink():
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            logger.exception(
                "tenant_import_archive_unlink_failed",
                extra={"job_id": str(job_id), "archive_path": str(path)},
            )

    # A crash after the database commit but before this callback leaves a repairable
    # orphan file discoverable from retention logs, never a rolled-back row naming a
    # file that was prematurely deleted.
    transaction.on_commit(unlink)
