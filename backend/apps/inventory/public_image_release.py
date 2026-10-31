"""Public image deletion and quota release after detachment commit."""
import logging

logger = logging.getLogger(__name__)


def release_public_image(makerspace, object_key, storage, *, guard):
    """Delete a public image object and free its quota only if the delete succeeded.

    The HEAD must precede the delete -- the size is unobtainable once the object is gone
    -- but the quota must be released only once the delete reported success. Freeing on a
    silent failure is the direction that permanently grants free storage, which is why
    every step is best-effort and a failure frees nothing.

    `storage` overrides the module the two calls resolve against. `apps.bookings.storage`
    wraps this with its own implementations, and its service layer takes `storage` as an
    injected dependency, so binding these to this module unconditionally would quietly
    step around that seam.
    """
    from apps.makerspaces import limits

    sizer = storage.object_size
    deleter = storage.delete_object

    size = None
    try:
        size = sizer(object_key)
    except Exception:
        logger.exception("Failed to size public image object before release: %s", object_key)
    guard.verify(makerspace.pk)
    try:
        deleted = deleter(object_key)
    except Exception:
        logger.exception("Failed to delete public image object during release: %s", object_key)
        return
    # Strict: only an affirmative True frees the quota. A deleter that reports nothing
    # cannot confirm anything, and treating silence as success is how a counter drifts
    # downward into permanently free storage.
    if not deleted or size is None:
        return
    guard.verify(makerspace.pk)
    try:
        limits.free_storage(makerspace, size)
    except Exception:
        logger.exception("Failed to free public image storage quota: %s", object_key)
