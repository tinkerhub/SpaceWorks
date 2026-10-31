import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.data_export.models import DataExportJob

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=DataExportJob)
def release_export_archive(sender, instance, **kwargs):
    """Delete and uncharge an archive after any committed row-deletion path."""
    from apps.makerspaces.purge_cleanup import owns_cleanup

    if owns_cleanup(instance.makerspace_id):
        return
    if not instance.object_key or getattr(instance, "_archive_released", False):
        return
    makerspace = instance.makerspace

    def release():
        from apps.data_export import storage
        from apps.makerspaces import limits
        from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
        from apps.tenant_migration.gate_runtime import tenant_write

        try:
            with tenant_write(makerspace.pk):
                if storage.delete_object(instance.object_key):
                    limits.free_storage(makerspace, instance.accounted_size_bytes)
        except SourceMigrationGateClosed:
            logger.info(
                "data_export_release_skipped_closed_source_gate",
                extra={"job_id": str(instance.pk), "makerspace_id": instance.makerspace_id},
            )
        except Exception:
            logger.exception(
                "data_export_archive_release_failed",
                extra={"job_id": str(instance.pk), "makerspace_id": instance.makerspace_id},
            )

    transaction.on_commit(release)
