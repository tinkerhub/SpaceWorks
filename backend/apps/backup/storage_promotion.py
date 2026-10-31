"""Remote byte operations for backup staging and create-only promotion."""

import hashlib
import hmac
import re
import tempfile

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings


CHUNK_SIZE = 1024 * 1024


def staging_locator(artifact_id):
    return f"backup-archives/staging/{artifact_id}.tar.age"


def final_locator(artifact_id):
    return f"backup-archives/deployment/{artifact_id}.tar.age"


def upload_staging(key, path):
    from apps.backup import storage

    storage.upload_archive(key, path)


def stream_verify(key, *, expected_size, expected_sha256):
    from apps.backup import storage

    body = None
    try:
        body = storage.client().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key
        )["Body"]
        digest = hashlib.sha256()
        size = 0
        while chunk := body.read(CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise storage.BackupStorageError(
            "The backup archive could not be streamed for verification."
        ) from exc
    finally:
        if body is not None and hasattr(body, "close"):
            body.close()
    actual = digest.hexdigest()
    if size != expected_size or not hmac.compare_digest(actual, expected_sha256):
        raise storage.BackupVerificationError(
            "The stored backup archive does not match its expected size and sha256."
        )
    return size, actual


def create_final_from_staging(
    staging_key, final_key, *, expected_size=None, expected_sha256=None
):
    """Verify a bounded disk spool, then publish it with `If-None-Match: *`.

    Production callers supply both expected facts. Legacy two-argument copies
    use GET ContentLength only as a spool bound, without authenticating a hash.
    """
    from apps.backup import storage

    source = None
    temporary = None
    failed = True
    try:
        if (expected_size is None) != (expected_sha256 is None) or (
            expected_size is not None
            and (
                type(expected_size) is not int
                or expected_size < 0
                or not isinstance(expected_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
            )
        ):
            raise storage.BackupVerificationError(
                "Backup promotion requires a nonnegative integer size and canonical sha256 together."
            )
        s3 = storage.client()
        response = s3.get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=staging_key
        )
        source = response["Body"]
        bound = expected_size
        if bound is None:
            bound = response.get("ContentLength")
            if type(bound) is not int or bound < 0:
                raise storage.BackupStorageError(
                    "The backup staging object has no valid content length for bounded promotion."
                )
        # TemporaryFile is a private, unlinked disk file, seekable by the SDK's
        # default checksum machinery, with bounded in-memory buffering.
        temporary = tempfile.TemporaryFile(mode="w+b")
        digest = hashlib.sha256()
        size = 0
        while chunk := source.read(min(CHUNK_SIZE, bound - size + 1)):
            if len(chunk) > bound - size:
                raise storage.BackupVerificationError(
                    "The stored backup archive does not match its expected size and sha256."
                )
            temporary.write(chunk)
            size += len(chunk)
            digest.update(chunk)
        actual = digest.hexdigest()
        if size != bound or (
            expected_sha256 is not None
            and not hmac.compare_digest(actual, expected_sha256)
        ):
            raise storage.BackupVerificationError(
                "The stored backup archive does not match its expected size and sha256."
            )
        temporary.seek(0)
        s3.put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=final_key,
            Body=temporary,
            ContentLength=size,
            ContentType="application/octet-stream",
            IfNoneMatch="*",
        )
        failed = False
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"PreconditionFailed", "ConditionalRequestConflict"} or status in {
            409, 412
        }:
            raise storage.BackupStorageError(
                "The immutable final backup locator already exists."
            ) from exc
        raise storage.BackupStorageError(
            "The backup staging object could not be promoted."
        ) from exc
    except (BotoCoreError, OSError) as exc:
        raise storage.BackupStorageError(
            "The backup staging object could not be promoted."
        ) from exc
    finally:
        # Attempt both closes, retaining the primary verification/SDK/I/O error.
        close_error = None
        for handle in (source, temporary):
            if handle is not None and hasattr(handle, "close"):
                try:
                    handle.close()
                except (BotoCoreError, ClientError, OSError) as exc:
                    close_error = exc
        if close_error is not None and not failed:
            raise storage.BackupStorageError(
                "The backup staging object could not be promoted."
            ) from close_error


def object_exists(key):
    from apps.backup import storage

    try:
        storage.client().head_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key
        )
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise storage.BackupStorageError(
            "The backup object locator could not be inspected."
        ) from exc
    except BotoCoreError as exc:
        raise storage.BackupStorageError(
            "The backup object locator could not be inspected."
        ) from exc
