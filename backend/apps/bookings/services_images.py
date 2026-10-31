from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from apps.accounts import rbac
from apps.makerspaces.guards import require_module

from apps.bookings.models import BookableSpace


def _locked_space(space_id):
    return (
        BookableSpace.objects.select_for_update()
        .select_related('makerspace')
        .get(pk=space_id)
    )


def validate_space_image_key(space, object_key, storage):
    if not storage.is_owned_object_key(space, object_key):
        raise serializers.ValidationError(
            {'object_key': 'Image object key is outside this space.'}
        )
    if not storage.has_allowed_extension(object_key):
        raise serializers.ValidationError(
            {'object_key': 'Image object key has an unsupported extension.'}
        )


def _active_space(space_id):
    locked = _locked_space(space_id)
    if not locked.is_active:
        raise serializers.ValidationError(
            {'space': 'Inactive spaces cannot have images changed.'}
        )
    return locked


def _assert_active(space):
    """Cheap unlocked pre-check, so an inactive space is refused without storage I/O.

    This is advisory only; `_active_space` repeats validation under the row lock.
    """
    if not space.is_active:
        raise serializers.ValidationError(
            {'space': 'Inactive spaces cannot have images changed.'}
        )


def cleanup_unattached_space_image(space, *, object_key, storage):
    # Unknown final ownership: compensate staging only.
    storage.delete_object(storage.staging_key(object_key))


def set_space_image(
    space,
    *,
    actor,
    object_key,
    size_bytes,
    audit,
    limits,
    storage,
    guard,
):
    locked = _active_space(space.pk)
    guard.verify(locked.makerspace_id)
    require_module(locked.makerspace_id, "bookings")
    if not rbac.can(actor, rbac.Action.MANAGE_BOOKINGS, locked.makerspace_id):
        raise PermissionDenied()
    validate_space_image_key(locked, object_key, storage)
    if object_key != locked.image_key and storage.public_image_key_in_use(locked.makerspace_id, object_key, space_id=locked.pk):
        raise serializers.ValidationError(
            {'object_key': 'This image is already in use.'}
        )
    old_key = locked.image_key
    if old_key == object_key:
        return locked
    limits.add_storage(locked.makerspace, size_bytes)
    locked.image_key = object_key
    locked.save(update_fields=['image_key', 'updated_at'])
    audit.record(
        actor,
        'booking.space_image_updated',
        makerspace=locked.makerspace,
        target=locked,
        meta={'replaced_image': bool(old_key)},
    )
    if old_key:
        storage.release_public_image_on_commit(locked.makerspace, old_key, guard=guard)
    locked.refresh_from_db()
    return locked


def remove_space_image(space, *, actor, audit, limits, storage, guard):
    _assert_active(space)
    locked = _active_space(space.pk)
    guard.verify(locked.makerspace_id)
    require_module(locked.makerspace_id, "bookings")
    if not rbac.can(actor, rbac.Action.MANAGE_BOOKINGS, locked.makerspace_id):
        raise PermissionDenied()
    if not locked.image_key:
        raise serializers.ValidationError({'image': 'This space has no image.'})
    validate_space_image_key(locked, locked.image_key, storage)
    old_key = locked.image_key
    locked.image_key = None
    locked.save(update_fields=['image_key', 'updated_at'])
    audit.record(
        actor,
        'booking.space_image_removed',
        makerspace=locked.makerspace,
        target=locked,
        meta={},
    )
    storage.release_public_image_on_commit(locked.makerspace, old_key, guard=guard)
    locked.refresh_from_db()
    return locked
