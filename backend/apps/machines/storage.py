"""Private-bucket storage for machine manuals/SOP documents.

Mirrors apps/warranty/storage.py: same PRIVATE evidence bucket, presign POST/PUT per
STORAGE_PRESIGN_METHOD, TOCTOU-safe finalize, and byte-sniff validation (%PDF- for PDFs,
image magic for images) — stronger than trusting the declared content type.
"""
from dataclasses import dataclass
import logging
import re
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.evidence.storage import StorageUnavailable
from apps.maker_file_formats import (
    ALLOWED_EXTENSIONS_BY_MIME,
    STRICT_MIME_BY_EXTENSION,
    allowed_pair,
    extension_from_name,
    has_required_signature,
    sniff_pdf_or_image,
)
from apps.object_storage import delete_accepted_object_versions

logger = logging.getLogger(__name__)
PDF_CONTENT_TYPE = "application/pdf"


@dataclass(frozen=True)
class MachineObjectValidationResult:
    size: int
    content_type: str


def _s3_client(endpoint_url):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(
            signature_version=settings.AWS_S3_SIGNATURE_VERSION,
            s3={"addressing_style": settings.AWS_S3_ADDRESSING_STYLE},
        ),
    )


def _client():
    return _s3_client(settings.AWS_S3_ENDPOINT_URL)


def _public_client():
    return _s3_client(settings.AWS_S3_PUBLIC_ENDPOINT_URL)


def machine_object_key(makerspace_id, machine_id, ext):
    safe_ext = str(ext).lower().lstrip(".")
    return f"machines/{makerspace_id}/{machine_id}/documents/{uuid.uuid4().hex}.{safe_ext}"


def staging_key(final_key):
    return f"staging/{final_key}"


def assert_machine_object_key_for_makerspace(object_key, makerspace_id, machine_id):
    prefix = f"machines/{makerspace_id}/{machine_id}/documents/"
    if not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}\.[a-z0-9]+", str(object_key)):
        raise ValidationError({
            "object_key": "Machine document key is not bound to this resource. Request a fresh upload URL."
        })


def ext_for(content_type, filename):
    ext = extension_from_name(filename)
    if not allowed_pair(
        ext,
        content_type,
        settings.MACHINE_DOC_ALLOWED_EXT,
        settings.MACHINE_DOC_ALLOWED_MIME,
    ):
        raise ValidationError({"filename": "Unsupported document extension or content type."})
    return ext


def presigned_upload(object_key, content_type):
    try:
        if settings.STORAGE_PRESIGN_METHOD == "put":
            url = _public_client().generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                    "Key": staging_key(object_key),
                    "ContentType": content_type,
                },
                ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
            )
            return {"url": url, "method": "PUT", "headers": {"Content-Type": content_type}}
        return _public_client().generate_presigned_post(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=staging_key(object_key),
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, settings.MACHINE_DOC_MAX_BYTES],
            ],
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def delete_object(object_key):
    try:
        delete_accepted_object_versions(
            _client(), bucket=settings.AWS_STORAGE_BUCKET_NAME, key=object_key
        )
    except (BotoCoreError, ClientError):
        logger.exception("Failed to delete machine document %s.", object_key)
        return False
    return True


def copy_object(source_key, dest_key):
    try:
        _client().copy_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            CopySource={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": source_key},
            Key=dest_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def object_size(object_key):
    try:
        response = _client().head_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
        )
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise StorageUnavailable from exc
    except BotoCoreError as exc:
        raise StorageUnavailable from exc
    return int(response["ContentLength"])


def finalize_upload(object_key, max_bytes):
    from apps.object_publication import InvalidObjectSize

    try:
        result = _publish_upload(object_key, max_bytes)
    except InvalidObjectSize as exc:
        return exc.size
    if result is not None:
        delete_object(staging_key(object_key))
    return result.size if result is not None else None


def presigned_get_url(object_key):
    try:
        return _public_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": object_key},
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def _validate_snapshot(object_key, observed):
    size, data = observed.size, observed.data()
    stored_content_type = observed.content_type
    ext = extension_from_name(object_key)
    if not allowed_pair(
        ext,
        stored_content_type,
        settings.MACHINE_DOC_ALLOWED_EXT,
        settings.MACHINE_DOC_ALLOWED_MIME,
    ):
        raise ValidationError(
            {"object_key": "Machine document extension and content type do not match."},
            code="invalid_document",
        )

    sniffed = sniff_pdf_or_image(data)
    strict_mime = STRICT_MIME_BY_EXTENSION.get(ext)
    if strict_mime or sniffed:
        if not strict_mime or stored_content_type != strict_mime or sniffed != strict_mime:
            raise ValidationError(
                {"object_key": "Machine document content does not match its extension."},
                code="invalid_document",
            )
        content_type = sniffed
    else:
        if not has_required_signature(ext, data):
            raise ValidationError(
                {"object_key": "Machine document signature is invalid."},
                code="invalid_document",
            )
        content_type = stored_content_type
    return MachineObjectValidationResult(size=size, content_type=content_type)


def validate_machine_object(object_key):
    from apps.object_publication import InvalidObjectSize, validate_existing

    try:
        result = validate_existing(
            _client(), settings.AWS_STORAGE_BUCKET_NAME, object_key,
            settings.MACHINE_DOC_MAX_BYTES, lambda observed: _validate_snapshot(object_key, observed),
        )
    except InvalidObjectSize as exc:
        raise ValidationError({"object_key": "Machine document is empty or exceeds the size limit."}) from exc
    if result is None:
        raise ValidationError({"object_key": "Machine document was not found."})
    return result


def prepare_upload(object_key, max_bytes=None):
    from apps.object_publication import InvalidObjectSize

    try:
        result = _publish_upload(object_key, max_bytes or settings.MACHINE_DOC_MAX_BYTES)
    except InvalidObjectSize as exc:
        raise ValidationError({"object_key": "Machine document is empty or exceeds the size limit."}) from exc
    if result is None:
        raise ValidationError({"object_key": "Machine document was not found."})
    delete_object(staging_key(object_key))
    return result


def _publish_upload(object_key, max_bytes):
    from apps.object_publication import publish

    return publish(
        _client(), bucket=settings.AWS_STORAGE_BUCKET_NAME, key=object_key,
        staging_key=staging_key(object_key), max_bytes=max_bytes or settings.MACHINE_DOC_MAX_BYTES,
        validator=lambda observed: _validate_snapshot(object_key, observed),
    )
