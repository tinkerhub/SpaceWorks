"""Synchronous local archive cleanup under the purge owner's exclusive fence."""

from pathlib import Path

from django.conf import settings

from .purge_storage import PurgeStorageRefused


def delete_import_archives(space):
    from apps.tenant_migration.models import TenantImportJob

    root = Path(settings.BACKUP_OPS_DIR, "tenant-imports").resolve()
    paths = []
    for value in TenantImportJob.objects.filter(target_makerspace=space).exclude(archive_path="").values_list("archive_path", flat=True):
        path = Path(value)
        if path.resolve().parent != root or path.suffixes != [".tar", ".age"] or path.is_symlink():
            raise PurgeStorageRefused("Tenant import archive path is outside its exact staging directory.")
        paths.append(path)
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise PurgeStorageRefused("Tenant import archive cleanup failed.") from exc
