"""Post-commit module-purge storage release under tenant lifecycle ownership."""
import logging

from django.conf import settings

from apps.object_storage import delete_all_versions
from apps.object_storage_references import private_key_in_use

logger = logging.getLogger(__name__)


def _delete_private_keys(keys, *, guard):
    """Best-effort delete of private objects; returns the keys the bucket confirmed gone.

    The return value is what lets the caller release storage quota for those keys only.
    A client that cannot even be constructed confirms nothing, so nothing is freed.
    """
    if not keys:
        return set()
    from apps.evidence import storage

    try:
        client = storage._client()
    except Exception:
        logger.exception("module_purge_storage_client_failed", extra={"keys": len(keys)})
        return set()
    deleted = set()
    for key in keys:
        guard.verify()
        if private_key_in_use(key):
            continue
        try:
            delete_all_versions(
                client, bucket=settings.AWS_STORAGE_BUCKET_NAME, key=key
            )
        except Exception:
            logger.exception("module_purge_storage_delete_failed: %s", key)
        else:
            deleted.add(key)
    if deleted:
        from apps.backup.models import RestoreRollbackObject

        RestoreRollbackObject.objects.filter(copy_key__in=deleted).delete()
    return deleted


def _collect_private_key_sizes(makerspace, plan):
    from apps.backup.models import RestoreRollbackObject

    sizes = plan.private_key_sizes(makerspace) if plan.private_key_sizes is not None else {}
    sizes.update({
        key: size for key, size in RestoreRollbackObject.objects.filter(
            makerspace=makerspace,
            module_key=plan.key,
            bucket_kind=RestoreRollbackObject.BucketKind.PRIVATE,
        ).exclude(copy_key="").values_list("copy_key", "size_bytes")
    })
    return sizes


def _free_private_storage(makerspace, sizes, deleted_keys):
    """Release charged bytes for private objects that were confirmed deleted."""
    if not sizes or not deleted_keys:
        return
    freed = sum(
        size for key, size in sizes.items() if size and key in deleted_keys
    )
    if not freed:
        return
    from apps.makerspaces import limits

    try:
        limits.free_storage(makerspace, freed)
    except Exception:
        logger.exception("module_purge_private_accounting_failed", extra={"bytes": freed})


def _delete_public_images_and_free_storage(makerspace, keys, *, guard):
    if not keys:
        return
    from apps.inventory import public_image_storage

    # Freeing first when a best-effort delete silently failed makes the counter
    # permanently wrong in the direction that grants free storage.
    for key in keys:
        guard.verify()
        from apps.object_storage_references import key_in_use
        if key_in_use("public_image", key):
            continue
        public_image_storage.release_public_image(makerspace, key, guard=guard)
        from apps.backup.models import RestoreRollbackObject

        RestoreRollbackObject.objects.filter(copy_key=key).delete()


