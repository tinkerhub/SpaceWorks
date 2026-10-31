from dataclasses import dataclass
import logging
import re
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.evidence.image_validation import image_mime_from_bytes
from apps.evidence.storage import StorageUnavailable
from apps.object_storage import delete_accepted_object_versions


logger = logging.getLogger(__name__)
PDF_CONTENT_TYPE = "application/pdf"
ALLOWED_EXTENSIONS_BY_MIME = {
    PDF_CONTENT_TYPE: {"pdf"},
    "image/jpeg": {"jpg", "jpeg"},
    "image/png": {"png"},
    "image/webp": {"webp"},
}


@dataclass(frozen=True)
class WarrantyObjectValidationResult:
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


def warranty_object_key(makerspace_id, warranty_id, ext):
    safe_ext = str(ext).lower().lstrip(".")
    return f"warranty/{makerspace_id}/{warranty_id}/documents/{uuid.uuid4().hex}.{safe_ext}"


def staging_key(final_key):
    return f"staging/{final_key}"


def assert_warranty_object_key_for_makerspace(object_key, makerspace_id, warranty_id):
    prefix = f"warranty/{makerspace_id}/{warranty_id}/documents/"
    if not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}\.[a-z0-9]+", str(object_key)):
        raise ValidationError({
            "object_key": "Warranty document key is not bound to this resource. Request a fresh upload URL."
        })


def ext_for(content_type, filename):
    allowed_mime = set(settings.WARRANTY_DOC_ALLOWED_MIME)
    allowed_exts = ALLOWED_EXTENSIONS_BY_MIME.get(content_type)
    if content_type not in allowed_mime or not allowed_exts:
        raise ValidationError({"content_type": "Unsupported warranty document type."})

    safe_name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if ext not in allowed_exts:
        raise ValidationError(
            {"filename": "Filename extension does not match the content type."}
        )
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
                ["content-length-range", 1, settings.WARRANTY_DOC_MAX_BYTES],
            ],
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def delete_object(object_key, *, report_versions=False):
    """Default boolean API; opt in to frozen DATA IDs or None on failure."""
    try:
        versions = delete_accepted_object_versions(
            _client(), bucket=settings.AWS_STORAGE_BUCKET_NAME, key=object_key,
            report_data_versions=report_versions,
        )
    except (BotoCoreError, ClientError):
        logger.exception("Failed to delete warranty document %s.", object_key)
        return None if report_versions else False
    return versions if report_versions else True


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
    content_type = PDF_CONTENT_TYPE if data.startswith(b"%PDF-") else None
    if content_type is None:
        image_type = image_mime_from_bytes(data)
        if image_type and image_type.startswith("image/"):
            content_type = image_type
    extension = str(object_key).rsplit(".", 1)[-1].lower()
    if extension not in ALLOWED_EXTENSIONS_BY_MIME.get(content_type, set()) or content_type != stored_content_type or content_type not in set(settings.WARRANTY_DOC_ALLOWED_MIME):
        raise ValidationError(
            {"object_key": "Warranty document is not a valid PDF or image."},
            code="invalid_document",
        )
    return WarrantyObjectValidationResult(size=size, content_type=content_type)


def validate_warranty_object(object_key):
    from apps.object_publication import InvalidObjectSize, validate_existing

    try:
        result = validate_existing(
            _client(), settings.AWS_STORAGE_BUCKET_NAME, object_key,
            settings.WARRANTY_DOC_MAX_BYTES, lambda observed: _validate_snapshot(object_key, observed),
        )
    except InvalidObjectSize as exc:
        raise ValidationError({"object_key": "Warranty document is empty or exceeds the size limit."}) from exc
    if result is None:
        raise ValidationError({"object_key": "Warranty document was not found."})
    return result


def prepare_upload(object_key, max_bytes=None):
    from apps.object_publication import InvalidObjectSize

    try:
        result = _publish_upload(object_key, max_bytes or settings.WARRANTY_DOC_MAX_BYTES)
    except InvalidObjectSize as exc:
        raise ValidationError({"object_key": "Warranty document is empty or exceeds the size limit."}) from exc
    if result is None:
        raise ValidationError({"object_key": "Warranty document was not found."})
    delete_object(staging_key(object_key))
    return result


def _publish_upload(object_key, max_bytes):
    from apps.object_publication import publish

    return publish(
        _client(), bucket=settings.AWS_STORAGE_BUCKET_NAME, key=object_key,
        staging_key=staging_key(object_key), max_bytes=max_bytes or settings.WARRANTY_DOC_MAX_BYTES,
        validator=lambda observed: _validate_snapshot(object_key, observed),
    )
