"""Private attachment storage for machine service requests."""
from dataclasses import dataclass
import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.evidence.storage import StorageUnavailable
from apps.maker_file_formats import (
    STRICT_MIME_BY_EXTENSION,
    allowed_pair,
    extension_from_name,
    has_required_signature,
    sniff_pdf_or_image,
)
from apps.machines import storage as machine_storage
from apps.machines.models import Machine, MachineServiceRequest, ServiceRequestFile
from apps.machines.service_file_policies import get_policy, policy_for_machine, policy_for_queue
from apps.makerspaces import limits
from apps.object_storage import delete_accepted_object_versions

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceObjectValidationResult:
    size: int
    content_type: str


def _client():
    return machine_storage._client()


def _public_client():
    return machine_storage._public_client()


def service_object_key(makerspace_id, context_id):
    return f"machine/{makerspace_id}/{context_id}/service/{uuid.uuid4().hex}"


def staging_key(object_key):
    return machine_storage.staging_key(object_key)


def validate_upload_declaration(policy, filename, content_type):
    ext = extension_from_name(filename)
    if not allowed_pair(ext, content_type, policy.allowed_extensions, policy.allowed_mimes):
        raise ValidationError({"filename": "Unsupported attachment extension or content type."}, code="invalid_attachment")


def policy_for_file(file):
    """Use the immutable policy snapshot retained with the staged file."""
    return get_policy(file.file_policy_name, file.file_policy_version)


def create_staged_file(service_request, *, actor, filename, content_type):
    if service_request.queue_id:
        queue = service_request.queue
        machine, policy, context_id = None, policy_for_queue(queue), f"queue-{queue.pk}"
        makerspace = queue.makerspace
    else:
        machine = Machine.objects.get(pk=service_request.bucket.machine_id)
        queue, policy, context_id, makerspace = None, policy_for_machine(machine), machine.pk, machine.makerspace
    validate_upload_declaration(policy, filename, content_type)
    upload = ServiceRequestFile.objects.create(
        makerspace=makerspace, machine=machine, queue=queue,
        kind=ServiceRequestFile.Kind.ATTACHMENT,
        object_key=service_object_key(makerspace.pk, context_id),
        content_type=content_type.lower().strip(),
        original_filename=filename,
        owner_user_id=actor.pk,
        file_policy_name=policy.name,
        file_policy_version=policy.version,
    )
    try:
        presigned = presigned_upload(upload.object_key, upload.content_type, policy.max_bytes)
    except Exception:
        upload.delete()
        raise
    audit.record(
        actor, "machine_service.file_staged", makerspace=makerspace,
        target=upload, meta={"request_id": service_request.pk, "file_id": upload.pk},
    )
    return upload, presigned


def create_staged_queue_file(queue, *, actor, filename, content_type, kind=ServiceRequestFile.Kind.MODEL):
    """Stage a public queued-service file before its request exists.

    Public printing uses this during the B4 compatibility period: the queue is
    already authoritative, while the request is only created after upload.
    """
    policy = policy_for_queue(queue)
    validate_upload_declaration(policy, filename, content_type)
    upload = ServiceRequestFile.objects.create(
        makerspace=queue.makerspace, queue=queue,
        kind=kind,
        object_key=service_object_key(queue.makerspace_id, f"queue-{queue.pk}"),
        content_type=content_type.lower().strip(), original_filename=filename,
        owner_user_id=actor.pk, file_policy_name=policy.name,
        file_policy_version=policy.version,
    )
    try:
        presigned = presigned_upload(upload.object_key, upload.content_type, policy.max_bytes)
    except Exception:
        upload.delete()
        raise
    audit.record(
        actor, "machine_service.file_staged", makerspace=queue.makerspace,
        target=upload, meta={"queue_id": queue.pk, "file_id": upload.pk},
    )
    return upload, presigned


def presigned_upload(object_key, content_type, max_bytes):
    try:
        if settings.STORAGE_PRESIGN_METHOD == "put":
            url = _public_client().generate_presigned_url(
                "put_object", Params={
                    "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                    "Key": staging_key(object_key), "ContentType": content_type,
                }, ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
            )
            return {"url": url, "method": "PUT", "headers": {"Content-Type": content_type}}
        return _public_client().generate_presigned_post(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=staging_key(object_key),
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def object_size(object_key):
    try:
        response = _client().head_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=object_key)
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise StorageUnavailable from exc
    except BotoCoreError as exc:
        raise StorageUnavailable from exc
    return int(response["ContentLength"])


def delete_object(object_key):
    try:
        delete_accepted_object_versions(
            _client(), bucket=settings.AWS_STORAGE_BUCKET_NAME, key=object_key
        )
    except (BotoCoreError, ClientError):
        logger.exception("Failed to delete machine service object %s.", object_key)
        return False
    return True


def cleanup_upload(object_key):
    # Final ownership is a metadata decision, never inferred from upload failure.
    delete_object(staging_key(object_key))


def finalize_upload(object_key, max_bytes, *, file=None):
    if file is None:
        file = ServiceRequestFile.objects.filter(object_key=object_key).first()
    if file is None or file.object_key != object_key:
        raise ValidationError({"file_id": "Attachment policy is required."}, code="invalid_attachment")
    from apps.object_publication import InvalidObjectSize

    try:
        result = _publish_file(file, max_bytes)
    except InvalidObjectSize as exc:
        return exc.size
    if result is not None:
        delete_object(staging_key(object_key))
    return result.size if result is not None else None


def prepare_file(file, *, max_bytes=None):
    from apps.object_publication import InvalidObjectSize

    try:
        result = _publish_file(file, max_bytes)
    except InvalidObjectSize as exc:
        raise ValidationError({"file_id": "Uploaded attachment is invalid."}, code="invalid_attachment") from exc
    if result is None:
        raise ValidationError({"file_id": "Uploaded attachment was not found."}, code="invalid_attachment")
    delete_object(staging_key(file.object_key))
    return result


def _publish_file(file, max_bytes=None):
    from apps.object_publication import publish

    policy = policy_for_file(file)
    return publish(
        _client(), bucket=settings.AWS_STORAGE_BUCKET_NAME, key=file.object_key,
        staging_key=staging_key(file.object_key), max_bytes=min(max_bytes or policy.max_bytes, policy.max_bytes),
        validator=lambda observed: _validate_snapshot(file, policy, observed),
    )


def _validate_snapshot(file, policy, observed):
    size, data, stored_content_type = observed.size, observed.data(), observed.content_type
    ext = extension_from_name(file.original_filename)
    if (stored_content_type != file.content_type.lower().strip()
            or not allowed_pair(ext, stored_content_type, policy.allowed_extensions, policy.allowed_mimes)):
        raise ValidationError({"file_id": "Attachment extension and content type do not match."}, code="invalid_attachment")
    sniffed = sniff_pdf_or_image(data)
    strict_mime = STRICT_MIME_BY_EXTENSION.get(ext)
    if strict_mime or sniffed:
        if not strict_mime or stored_content_type != strict_mime or sniffed != strict_mime:
            raise ValidationError({"file_id": "Attachment content does not match its extension."}, code="invalid_attachment")
        content_type = sniffed
    elif not has_required_signature(ext, data):
        raise ValidationError({"file_id": "Attachment signature is invalid."}, code="invalid_attachment")
    else:
        content_type = stored_content_type
    return ServiceObjectValidationResult(size=size, content_type=content_type)


def validate_service_object(file, policy):
    from apps.object_publication import InvalidObjectSize, validate_existing

    try:
        result = validate_existing(
            _client(), settings.AWS_STORAGE_BUCKET_NAME, file.object_key, policy.max_bytes,
            lambda observed: _validate_snapshot(file, policy, observed),
        )
    except InvalidObjectSize as exc:
        raise ValidationError({"file_id": "Uploaded attachment is invalid."}, code="invalid_attachment") from exc
    if result is None:
        raise ValidationError({"file_id": "Uploaded attachment was not found."}, code="invalid_attachment")
    return result


def finalize_file(service_request, *, file_id, actor, guard=None, prepared=None, authorize=None):
    from apps.machines.service_file_lifecycle import finalize_file as implementation

    return implementation(service_request, file_id=file_id, actor=actor, guard=guard, prepared=prepared, authorize=authorize)


def delete_staged_file(file, *, actor, guard=None, authorize=None):
    from apps.machines.service_file_lifecycle import delete_staged_file as implementation

    return implementation(file, actor=actor, guard=guard, authorize=authorize)


def presigned_get_url(object_key):
    try:
        return _public_client().generate_presigned_url(
            "get_object", Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": object_key},
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc
