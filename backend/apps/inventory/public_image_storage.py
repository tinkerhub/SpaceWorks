from dataclasses import dataclass
import logging
import time
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import transaction

from apps.evidence.storage import StorageUnavailable
from apps.inventory.public_image_metadata import (
    ext_for,
    public_image_key_in_use,
    public_url,
)
from apps.inventory.public_image_sniff import sniff_is_valid_image
from apps.object_storage import delete_accepted_object_versions


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinalizeResult:
    status: str
    size: int | None


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


def build_object_key(kind, makerspace_id, ext):
    if kind not in {"event", "event-series", "items", "machine", "makerspace", "member", "printers"}:
        raise ValueError("Invalid public image kind.")
    return f"{kind}/{makerspace_id}/{uuid.uuid4().hex}{ext}"


def staging_key(final_key):
    return f"staging/{final_key}"


def is_safe_object_key(object_key):
    if object_key.startswith("/") or "\\" in object_key or ".." in object_key:
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in object_key)


def delete_object(object_key):
    if not object_key:
        return True
    try:
        delete_accepted_object_versions(
            _client(), bucket=settings.PUBLIC_IMAGE_BUCKET, key=object_key
        )
    except (BotoCoreError, ClientError):
        logger.exception("Failed to delete public image object %s.", object_key)
        return False
    return True


def release_public_image(makerspace, object_key, storage=None, *, guard=None):
    import sys
    from apps.inventory.public_image_release import release_public_image as implementation

    if guard is None:
        raise StorageUnavailable
    return implementation(makerspace, object_key, storage or sys.modules[__name__], guard=guard)


def release_public_image_on_commit(makerspace, object_key, storage=None, *, guard=None):
    from apps.inventory.tenant_object_callbacks import release_public_image
    from apps.makerspaces.purge_cleanup import owns_cleanup

    if owns_cleanup(makerspace.pk):
        return
    if guard is None:
        # An uncoordinated detach must leave conservative orphan accounting; it
        # must never delete a key another lifecycle can already have reattached.
        logger.error("public_image_cleanup_missing_guard", extra={"makerspace_id": makerspace.pk})
        return
    guard.verify(makerspace.pk)
    transaction.on_commit(lambda: release_public_image(makerspace, object_key, storage, guard=guard))


def delete_public_image_on_commit(makerspace, object_key, *, guard=None):
    from apps.inventory.tenant_object_callbacks import delete_public_image
    from apps.makerspaces.purge_cleanup import owns_cleanup

    if owns_cleanup(makerspace.pk):
        return
    if guard is None:
        logger.error("public_image_cleanup_missing_guard", extra={"makerspace_id": makerspace.pk})
        return
    guard.verify(makerspace.pk)
    transaction.on_commit(lambda: delete_public_image(makerspace.pk, object_key, guard=guard))


def put_bytes(object_key, data, content_type):
    try:
        _client().put_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc

def copy_object(source_key, dest_key):
    try:
        _client().copy_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            CopySource={
                "Bucket": settings.PUBLIC_IMAGE_BUCKET,
                "Key": source_key,
            },
            Key=dest_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def object_exists(object_key):
    try:
        _client().head_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=object_key,
        )
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise StorageUnavailable from exc
    except BotoCoreError as exc:
        raise StorageUnavailable from exc
    return True


def object_size(object_key):
    try:
        response = _client().head_object(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
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



def object_size_after_upload(object_key, attempts=10, delay_seconds=0.2):
    for attempt in range(attempts):
        size = object_size(object_key)
        if size is not None or attempt == attempts - 1:
            return size
        time.sleep(delay_seconds)
    return None


def _finalize_result(object_key, size):
    max_bytes = settings.PUBLIC_IMAGE_MAX_BYTES
    if size is None:
        result = FinalizeResult("missing", None)
    elif size == 0:
        result = FinalizeResult("empty", size)
    elif size > max_bytes:
        result = FinalizeResult("too_large", size)
    else:
        result = FinalizeResult("ok", size)

    if result.status != "ok":
        logger.warning(
            "Invalid public image upload: status=%s object_key=%s bucket=%s "
            "endpoint=%s storage_presign_method=%s max_bytes=%s observed_size=%s",
            result.status,
            object_key,
            settings.PUBLIC_IMAGE_BUCKET,
            settings.AWS_S3_ENDPOINT_URL,
            settings.STORAGE_PRESIGN_METHOD,
            max_bytes,
            result.size,
        )
    return result


def finalize_error_message(result):
    if result.status == "invalid":
        return "Uploaded file is not a valid image."
    if result.status == "missing":
        return "Uploaded image was not found in storage."
    if result.status == "empty":
        return "Uploaded image is empty (0 bytes)."
    if result.status == "too_large":
        max_mb = settings.PUBLIC_IMAGE_MAX_BYTES // (1024 * 1024)
        return f"Uploaded image exceeds the {max_mb} MB limit."
    return "Uploaded file is not a valid image."


def presigned_upload(object_key, content_type):
    try:
        if settings.STORAGE_PRESIGN_METHOD == "put":
            # Presigned PUT cannot enforce content-length at upload time; finalize HEADs staging.
            url = _public_client().generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.PUBLIC_IMAGE_BUCKET,
                    "Key": staging_key(object_key),
                    "ContentType": content_type,
                },
                ExpiresIn=settings.PUBLIC_IMAGE_URL_TTL_SECONDS,
            )
            return {
                "url": url,
                "method": "PUT",
                "headers": {"Content-Type": content_type},
            }
        return _public_client().generate_presigned_post(
            Bucket=settings.PUBLIC_IMAGE_BUCKET,
            Key=staging_key(object_key),
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, settings.PUBLIC_IMAGE_MAX_BYTES],
            ],
            ExpiresIn=settings.PUBLIC_IMAGE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def finalize_upload(object_key):
    import sys
    from apps.inventory.public_image_publication import finalize

    return finalize(sys.modules[__name__], object_key)
