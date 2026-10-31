"""Audited mutation boundary for the Event cover image.

Split out of services.py to keep that module under the file-size ceiling, mirroring
apps/bookings/services_images.py. The image key is deliberately not part of
services.EVENT_FIELDS: it is owned by the dedicated image endpoints, so a generic
event update can never set or clear it.
"""

from apps.object_storage_lifecycle import storage_lifecycle

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.events.organizer_authority import can_manage_event
from apps.makerspaces.guards import require_module

from apps.audit import services as audit
from apps.events.models import Event
from apps.inventory import public_image_storage
from apps.makerspaces import limits


def _locked_event(event_id):
    return (
        Event.objects.select_for_update()
        .select_related("makerspace")
        .get(pk=event_id)
    )


def update_image(event, actor, object_key, *, size_bytes=None, guard=None):
    with storage_lifecycle(event.makerspace_id, guard=guard) as owned:
        if size_bytes is None:
            result = public_image_storage.finalize_upload(object_key)
            if result.status != "ok":
                raise ValidationError({"object_key": public_image_storage.finalize_error_message(result)})
            size_bytes = result.size
        owned.verify()
        with transaction.atomic():
            return _update_image(event, actor, object_key, size_bytes=size_bytes, guard=owned)


def _update_image(event, actor, object_key, *, size_bytes, guard):
    locked = _locked_event(event.pk)
    guard.verify(locked.makerspace_id)
    require_module(locked.makerspace_id, "events")
    if not can_manage_event(actor, locked):
        raise PermissionDenied()
    old_key = locked.image_key
    if object_key == old_key:
        return locked
    if object_key and public_image_storage.public_image_key_in_use(
        locked.makerspace_id,
        object_key,
        event_id=locked.pk,
    ):
        raise ValidationError({"object_key": "This image is already in use."})
    limits.add_storage(locked.makerspace, size_bytes)
    if old_key:
        public_image_storage.release_public_image_on_commit(
            locked.makerspace, old_key, guard=guard
        )
    locked.image_key = object_key
    update_fields = ["image_key", "updated_at"]
    if locked.series_id:
        locked.series_override_fields = sorted(
            set(locked.series_override_fields or []) | {"image_key"}
        )
        update_fields.append("series_override_fields")
    locked.save(update_fields=update_fields)
    audit.record(
        actor,
        "event.image_updated",
        makerspace=locked.makerspace,
        target=locked,
        meta={"replaced_image": bool(old_key)},
    )
    locked.refresh_from_db()
    return locked


def remove_image(event, actor, *, guard=None):
    with storage_lifecycle(event.makerspace_id, guard=guard) as owned:
        owned.verify()
        with transaction.atomic():
            return _remove_image(event, actor, guard=owned)


def _remove_image(event, actor, *, guard):
    locked = _locked_event(event.pk)
    guard.verify(locked.makerspace_id)
    require_module(locked.makerspace_id, "events")
    if not can_manage_event(actor, locked):
        raise PermissionDenied()
    old_key = locked.image_key
    if not old_key and (
        locked.series_id is None or "image_key" in (locked.series_override_fields or [])
    ):
        return locked
    locked.image_key = ""
    update_fields = ["image_key", "updated_at"]
    if locked.series_id:
        locked.series_override_fields = sorted(
            set(locked.series_override_fields or []) | {"image_key"}
        )
        update_fields.append("series_override_fields")
    locked.save(update_fields=update_fields)
    audit.record(
        actor,
        "event.image_removed",
        makerspace=locked.makerspace,
        target=locked,
        meta={},
    )
    public_image_storage.release_public_image_on_commit(locked.makerspace, old_key, guard=guard)
    locked.refresh_from_db()
    return locked
