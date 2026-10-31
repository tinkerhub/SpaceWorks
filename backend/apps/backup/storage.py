"""Private storage for age-encrypted archives."""

import logging

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.object_storage import delete_all_versions

logger = logging.getLogger(__name__)
# Shared by every uploader: apps.*.storage.staging_key() is f"staging/{final_key}".
STAGING_PREFIX = "staging/"

RESTORABLE_HEADERS = (
    "CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage",
    "ContentType", "Expires", "WebsiteRedirectLocation",
)


class BackupStorageError(RuntimeError):
    pass


class MissingBackupObject(BackupStorageError):
    """The current object and, when versioned, all retained versions are absent."""


class BackupVerificationError(BackupStorageError):
    pass

def client(*, public_endpoint=False):
    endpoint = settings.AWS_S3_PUBLIC_ENDPOINT_URL if public_endpoint else settings.AWS_S3_ENDPOINT_URL
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


def upload_archive(key, path):
    try:
        with open(path, "rb") as handle:
            client().upload_fileobj(
                handle,
                settings.AWS_STORAGE_BUCKET_NAME,
                key,
                ExtraArgs={"ContentType": "application/octet-stream"},
            )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise BackupStorageError("The encrypted backup archive could not be stored.") from exc


def copy_archive(source_key, destination_key):
    """Compatibility name for the create-only final-object promotion primitive."""
    return create_final_from_staging(source_key, destination_key)


def open_archive(key):
    try:
        return client().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key
        )["Body"]
    except (BotoCoreError, ClientError) as exc:
        raise BackupStorageError("The encrypted backup archive could not be opened.") from exc


def delete_archive(key):
    try:
        s3 = client()
        delete_all_versions(
            s3, bucket=settings.AWS_STORAGE_BUCKET_NAME, key=key
        )
        return True
    except (BotoCoreError, ClientError):
        logger.exception("backup_archive_delete_failed", extra={"object_key": key})
        return False


def delete_archive_prefix(prefix):
    """Delete every retained version and current object below a staging prefix."""
    try:
        s3 = client()
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        key_marker = version_marker = None
        found_versions = False
        try:
            while True:
                params = {"Bucket": bucket, "Prefix": prefix}
                if key_marker:
                    params["KeyMarker"] = key_marker
                if version_marker:
                    params["VersionIdMarker"] = version_marker
                page = s3.list_object_versions(**params)
                objects = [
                    {"Key": item["Key"], "VersionId": item["VersionId"]}
                    for group in (
                        page.get("Versions", []),
                        page.get("DeleteMarkers", []),
                    )
                    for item in group
                ]
                if objects:
                    found_versions = True
                    s3.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": objects, "Quiet": True},
                    )
                if not page.get("IsTruncated"):
                    break
                key_marker = page.get("NextKeyMarker")
                version_marker = page.get("NextVersionIdMarker")
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"NotImplemented", "InvalidRequest", "501"}:
                raise
        if not found_versions:
            continuation_token = None
            while True:
                params = {"Bucket": bucket, "Prefix": prefix}
                if continuation_token:
                    params["ContinuationToken"] = continuation_token
                page = s3.list_objects_v2(**params)
                objects = [
                    {"Key": item["Key"]} for item in page.get("Contents", [])
                ]
                if objects:
                    s3.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": objects, "Quiet": True},
                    )
                if not page.get("IsTruncated"):
                    break
                continuation_token = page.get("NextContinuationToken")
        return True
    except (BotoCoreError, ClientError):
        logger.exception(
            "backup_archive_prefix_delete_failed", extra={"prefix": prefix}
        )
        return False


def ensure_versioning_or_quiescence(bucket):
    """Return versioned when the backend can guarantee version IDs, else quiesced."""
    s3 = client()
    try:
        status = s3.get_bucket_versioning(Bucket=bucket).get("Status")
        if status == "Enabled":
            return "versioned"
        s3.put_bucket_versioning(
            Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
        )
        status = s3.get_bucket_versioning(Bucket=bucket).get("Status")
        return "versioned" if status == "Enabled" else "quiesced"
    except (BotoCoreError, ClientError):
        return "quiesced"


def download_object(bucket, key, destination, *, versioned):
    """Capture one object, using staging only when the final object is absent.

    Every uploader presigns `staging/{key}` and only promotes the bytes to `key`
    when a workflow consumes them, so an uploaded-but-unconsumed object exists
    ONLY in staging while its row already names the final key. Capture used to
    treat that as fatal, meaning a single pending upload could block a tenant
    backup or migration. The staged bytes are recorded under the FINAL key so a
    restore lands them where every app's read path looks first; promotion still
    validates them, because each finalizer validates the final object when it
    finds one.
    """
    try:
        return _download_object(bucket, key, destination, versioned=versioned)
    except MissingBackupObject:
        if key.startswith(STAGING_PREFIX):
            raise
        staged = _download_object(
            bucket, f"{STAGING_PREFIX}{key}", destination, versioned=versioned
        )
        logger.warning(
            "backup_captured_staged_object",
            extra={"bucket": bucket, "key": key},
        )
        return {**staged, "key": key}


def assert_object_absent(bucket, key):
    """Fail closed if a terminal retention tombstone still has any stored bytes."""
    s3 = client()
    try:
        page = s3.list_object_versions(Bucket=bucket, Prefix=key)
        while True:
            for group in (page.get("Versions", ()), page.get("DeleteMarkers", ())):
                if any(item.get("Key") == key for item in group):
                    raise BackupStorageError(
                        f"Expired storage object {key} still has retained versions."
                    )
            if not page.get("IsTruncated"):
                break
            params = {
                "Bucket": bucket,
                "Prefix": key,
                "KeyMarker": page.get("NextKeyMarker"),
                "VersionIdMarker": page.get("NextVersionIdMarker"),
            }
            page = s3.list_object_versions(
                **{name: value for name, value in params.items() if value is not None}
            )
    except ClientError as exc:
        raise BackupStorageError(
            f"Expired storage object {key} could not be inspected."
        ) from exc
    except BotoCoreError as exc:
        raise BackupStorageError(
            f"Expired storage object {key} could not be inspected."
        ) from exc
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return
        raise BackupStorageError(
            f"Expired storage object {key} could not be inspected."
        ) from exc
    except BotoCoreError as exc:
        raise BackupStorageError(
            f"Expired storage object {key} could not be inspected."
        ) from exc
    raise BackupStorageError(f"Expired storage object {key} is still present.")

def _download_object(bucket, key, destination, *, versioned):
    # Resolve dependencies here so existing storage-module monkeypatches still apply.
    from .storage_capture import download_object as capture_object

    return capture_object(
        bucket, key, destination, versioned=versioned, s3=client(),
        restorable_headers=RESTORABLE_HEADERS,
        latest_retained_version=_latest_retained_version,
    )


def _latest_retained_version(s3, bucket, key):
    from .storage_capture import latest_retained_version

    return latest_retained_version(s3, bucket, key)


from .storage_promotion import create_final_from_staging, final_locator, object_exists, staging_locator, stream_verify, upload_staging  # noqa: E402,F401
