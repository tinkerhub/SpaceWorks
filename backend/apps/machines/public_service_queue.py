"""Deterministic, audited first-POST setup and stable attachment queue pinning."""
from rest_framework.exceptions import APIException, ValidationError

from apps.audit import services as audit
from apps.machines.models import ServiceQueue, ServiceRequestFile


class PublicServiceQueueConflict(APIException):
    status_code = 409
    default_code = "public_service_queue_conflict"
    default_detail = "Public service queue is inactive or its default name is in use. Ask staff to configure it."


def attachment_queue_id(makerspace, actor, file_ids, pinned_id):
    """Read before locking queues; lock and recheck the files after the queue."""
    if not file_ids:
        return pinned_id
    files = list(_owned_files(makerspace, actor, file_ids))
    queue_ids = {file.queue_id for file in files}
    if len(files) != len(set(file_ids)) or len(queue_ids) != 1 or None in queue_ids:
        raise ValidationError({"file_ids": "Uploads must be unused, yours, and from one queue."})
    queue_id = queue_ids.pop()
    if pinned_id is not None and pinned_id != queue_id:
        raise ValidationError({"queue_id": "Queue does not match the uploaded files."})
    return queue_id


def _owned_files(makerspace, actor, file_ids):
    return ServiceRequestFile.objects.filter(
        pk__in=file_ids, makerspace=makerspace, owner_user_id=actor.pk,
        service_request__isnull=True, attached_at__isnull=True,
    )


def lock_attachments(makerspace, actor, file_ids, queue):
    files = list(_owned_files(makerspace, actor, file_ids).select_for_update().order_by("pk"))
    if len(files) != len(set(file_ids)) or any(file.queue_id != queue.pk for file in files):
        raise ValidationError({"file_ids": "Uploads are invalid, already used, or belong to another queue."})
    return files


def validate_requested_queue(makerspace, machine_type, queue_id):
    """Read-only preflight; authoritative queue resolution still happens under locks."""
    if queue_id is None:
        return
    queue = ServiceQueue.objects.filter(
        makerspace=makerspace, machine_type=machine_type, pk=queue_id,
    ).first()
    if queue is None:
        raise ValidationError({"queue_id": "Queue is unavailable for this machine type."})
    if not queue.is_active:
        raise PublicServiceQueueConflict()


def resolve_intake_queue(makerspace, machine_type, actor, *, queue_id=None):
    """Caller holds the PII fence and makerspace NO KEY UPDATE lock."""
    rows = ServiceQueue.objects.select_for_update().filter(
        makerspace=makerspace, machine_type=machine_type,
    ).order_by("name", "pk")
    if queue_id is not None:
        queue = rows.filter(pk=queue_id).first()
        if queue is None:
            raise ValidationError({"queue_id": "Queue is unavailable for this machine type."})
        if not queue.is_active:
            raise PublicServiceQueueConflict()
        return queue
    active = rows.filter(is_active=True).first()
    if active is not None:
        return active
    if rows.exists():
        raise PublicServiceQueueConflict()
    name = f"Public Requests - type {machine_type.pk}"
    if ServiceQueue.objects.filter(makerspace=makerspace, name=name).exists():
        raise PublicServiceQueueConflict()
    queue = ServiceQueue.objects.create(makerspace=makerspace, machine_type=machine_type, name=name)
    audit.record(actor, "machine_service.public_queue_created", makerspace=makerspace, target=queue)
    return queue
