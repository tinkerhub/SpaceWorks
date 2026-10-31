from apps.object_storage_lifecycle import storage_lifecycle
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.events.series_authority import can_manage_series
from apps.makerspaces.guards import require_module

from apps.audit import services as audit
from apps.events.models import EventSeries
from apps.inventory import public_image_storage
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked


def update_image(series, actor, object_key, *, size_bytes=None, guard=None):
    with storage_lifecycle(series.makerspace_id, guard=guard) as owned:
        if size_bytes is None:
            result = public_image_storage.finalize_upload(object_key)
            if result.status != "ok":
                raise ValidationError({"object_key": public_image_storage.finalize_error_message(result)})
            size_bytes = result.size
        owned.verify()
        with transaction.atomic():
            return _update_image(series, actor, object_key, size_bytes=size_bytes, guard=owned)


def _update_image(series, actor, object_key, *, size_bytes, guard):
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    require_module_locked(locked.makerspace_id, "events")
    guard.verify(locked.makerspace_id)
    require_module(locked.makerspace_id, "events")
    if not can_manage_series(actor, locked):
        raise PermissionDenied()
    old_key = locked.image_key
    if object_key == old_key:
        return locked
    if public_image_storage.public_image_key_in_use(
        locked.makerspace_id, object_key, series_id=locked.pk
    ):
        raise ValidationError({"object_key": "This image is already in use."})
    limits.add_storage(locked.makerspace, size_bytes)
    if old_key:
        public_image_storage.release_public_image_on_commit(locked.makerspace, old_key, guard=guard)
    locked.image_key = object_key
    locked.save(update_fields=("image_key", "updated_at"))
    audit.record(
        actor, "event.series_image_updated", makerspace=locked.makerspace,
        target=locked, meta={"replaced_image": bool(old_key)},
    )
    return locked


def remove_image(series, actor, *, guard=None):
    with storage_lifecycle(series.makerspace_id, guard=guard) as owned:
        owned.verify()
        with transaction.atomic():
            return _remove_image(series, actor, guard=owned)


def _remove_image(series, actor, *, guard):
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    require_module_locked(locked.makerspace_id, "events")
    guard.verify(locked.makerspace_id)
    require_module(locked.makerspace_id, "events")
    if not can_manage_series(actor, locked):
        raise PermissionDenied()
    old_key = locked.image_key
    if not old_key:
        return locked
    locked.image_key = ""
    locked.save(update_fields=("image_key", "updated_at"))
    audit.record(
        actor, "event.series_image_removed", makerspace=locked.makerspace, target=locked
    )
    public_image_storage.release_public_image_on_commit(locked.makerspace, old_key, guard=guard)
    return locked
