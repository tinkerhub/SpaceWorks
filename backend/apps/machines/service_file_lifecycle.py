"""Service attachment metadata changes under explicit tenant storage ownership."""
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.encryption.write_fence import assert_mapped_write_allowed
from apps.machines import service_storage as storage
from apps.machines.models import MachineServiceRequest, ServiceRequestFile
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace
from apps.object_storage_lifecycle import storage_lifecycle


@dataclass(frozen=True)
class PreparedFile:
    identity: tuple
    metadata: object


def _identity(file):
    return (file.pk, file.kind, file.makerspace_id, file.owner_user_id, file.queue_id, file.machine_id,
            file.object_key, file.original_filename, file.content_type,
            file.file_policy_name, file.file_policy_version)


def _prepare(file):
    return PreparedFile(_identity(file), storage.prepare_file(file))


def _unavailable():
    return ValidationError({"file_id": "Attachment is unavailable for this request."}, code="invalid_attachment")


def pending_file(file_id, actor, makerspace_id=None):
    row = ServiceRequestFile.objects.filter(pk=file_id, owner_user_id=actor.pk).first()
    if (row is None or row.service_request_id is not None or row.attached_at is not None
            or (makerspace_id is not None and row.makerspace_id != makerspace_id)):
        raise _unavailable()
    return row


def prepare_files(makerspace_id, ids, actor, guard):
    guard.verify(makerspace_id)
    if transaction.get_connection().in_atomic_block:
        from apps.evidence.storage import StorageUnavailable
        raise StorageUnavailable
    # Validate every attachment before the first object can be published.
    files = [pending_file(file_id, actor, makerspace_id) for file_id in dict.fromkeys(ids)]
    return {file.pk: _prepare(file) for file in files}


def finalize_file(service_request, *, file_id, actor, guard=None, prepared=None, authorize=None):
    with storage_lifecycle(service_request.makerspace_id, guard=guard) as owned:
        file = pending_file(file_id, actor, service_request.makerspace_id)
        if prepared is None and transaction.get_connection().in_atomic_block:
            from apps.evidence.storage import StorageUnavailable
            raise StorageUnavailable
        preparation = prepared if prepared is not None else _prepare(file)
        result = preparation.metadata
        owned.verify()
        # Preserve the service PII fence -> NO KEY UPDATE space -> request/file order.
        with transaction.atomic():
            assert_mapped_write_allowed(service_request.makerspace_id)
            Makerspace.objects.select_for_update(no_key=True).get(pk=service_request.makerspace_id)
            locked_request = MachineServiceRequest.objects.select_for_update(of=("self",)).select_related(
                "bucket__machine__makerspace", "queue__makerspace"
            ).get(pk=service_request.pk)
            locked_file = ServiceRequestFile.objects.select_for_update().get(pk=file.pk)
            if (
                _identity(locked_file) != preparation.identity
                or locked_file.owner_user_id != actor.pk
                or locked_file.service_request_id is not None or locked_file.attached_at is not None
                or locked_file.object_key != file.object_key
                or locked_file.file_policy_name != file.file_policy_name
                or locked_file.file_policy_version != file.file_policy_version
                or locked_file.original_filename != file.original_filename
                or locked_file.makerspace_id != locked_request.makerspace_id
                or (locked_request.queue_id and locked_file.queue_id != locked_request.queue_id)
                or (locked_request.bucket_id and locked_file.machine_id != locked_request.bucket.machine_id)
            ):
                raise _unavailable()
            if authorize is not None:
                authorize()
            owned.verify()
            limits.add_storage(locked_request.makerspace, result.size, no_key=True)
            locked_file.service_request = locked_request
            locked_file.attached_at = timezone.now()
            locked_file.size_bytes, locked_file.content_type = result.size, result.content_type
            locked_file.save(update_fields=["service_request", "attached_at", "size_bytes", "content_type"])
            audit.record(
                actor, "machine_service.file_attached", makerspace=locked_request.makerspace,
                target=locked_file, meta={"request_id": locked_request.pk, "file_id": locked_file.pk, "size_bytes": result.size},
            )
            return locked_file
        # No final compensation: a failed metadata transaction may leave an orphan,
        # but can never remove an accepted winner (including legacy references).


def delete_staged_file(file, *, actor, guard=None, authorize=None):
    with storage_lifecycle(file.makerspace_id, guard=guard) as owned:
        with transaction.atomic():
            locked = ServiceRequestFile.objects.select_for_update(of=("self",)).select_related("makerspace").get(pk=file.pk)
            if locked.service_request_id is not None or locked.attached_at is not None:
                raise _unavailable()
            if authorize is not None:
                authorize()
            owned.verify()
            audit.record(actor, "machine_service.file_deleted", makerspace=locked.makerspace,
                         target=locked, meta={"file_id": locked.pk, "size_bytes": locked.size_bytes})
            key, space, size = locked.object_key, locked.makerspace, locked.size_bytes
            locked.delete()
        owned.verify()
        from apps.object_storage_references import private_key_in_use
        if not private_key_in_use(key):
            owned.verify()
            if storage.delete_object(key):
                owned.verify()
                limits.free_storage(space, size)
        storage.delete_object(storage.staging_key(key))
