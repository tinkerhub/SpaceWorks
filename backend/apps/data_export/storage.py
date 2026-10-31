"""Private object-storage operations for completed export archives."""

import logging

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.object_storage import delete_all_versions

from .models import DataExportJob
from .object_lock import export_object_lock
from .source_boundary import gated_archive_upload

logger = logging.getLogger(__name__)


class ExportStorageError(RuntimeError):
    pass


def _client(*, public=False):
    endpoint = (
        settings.AWS_S3_PUBLIC_ENDPOINT_URL if public else settings.AWS_S3_ENDPOINT_URL
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(
            signature_version=settings.AWS_S3_SIGNATURE_VERSION,
            s3={"addressing_style": settings.AWS_S3_ADDRESSING_STYLE},
        ),
    )


@gated_archive_upload
def upload_archive(object_key, file_path, content_type="application/zip"):
    # Both REDACTED and PORTABLE producers use this boundary. A worker still
    # building when recovery wins must never republish a deleted/failed archive.
    from .lifecycle import require_running

    with export_object_lock(object_key):
        require_running(DataExportJob.objects.filter(object_key=object_key).first())
        _upload_archive_bytes(object_key, file_path, content_type)


def _upload_archive_bytes(object_key, file_path, content_type):
    from apps.tenant_migration.gate_runtime import assert_boundary_held
    from .errors import ExportIntegrityError

    makerspace_id = DataExportJob.objects.filter(object_key=object_key).values_list(
        "makerspace_id", flat=True,
    ).first()
    if makerspace_id is None:
        raise ExportIntegrityError("The raw export upload has no owning job.")
    assert_boundary_held(makerspace_id)
    try:
        with open(file_path, "rb") as handle:
            _client().upload_fileobj(
                handle,
                settings.AWS_STORAGE_BUCKET_NAME,
                object_key,
                ExtraArgs={"ContentType": content_type},
            )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise ExportStorageError("The export archive could not be stored.") from exc


def open_archive(object_key):
    try:
        response = _client().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
        )
        return response["Body"]
    except (BotoCoreError, ClientError) as exc:
        raise ExportStorageError("The export archive could not be opened.") from exc


def object_size(object_key):
    try:
        response = _client().head_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=object_key,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return None
        raise ExportStorageError("The export archive could not be sized.") from exc
    except BotoCoreError as exc:
        raise ExportStorageError("The export archive could not be sized.") from exc
    return int(response["ContentLength"])


def delete_object(object_key):
    """Return True only when the bucket accepted deletion (missing is also success)."""
    if not object_key:
        return True
    try:
        delete_all_versions(
            _client(), bucket=settings.AWS_STORAGE_BUCKET_NAME, key=object_key
        )
        return True
    except (BotoCoreError, ClientError):
        logger.exception("data_export_archive_delete_failed", extra={"object_key": object_key})
        return False
