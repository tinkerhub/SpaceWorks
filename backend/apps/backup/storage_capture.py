"""Capture current or retained object bytes without masking storage failures."""

import hashlib

from botocore.exceptions import BotoCoreError, ClientError

from .storage import BackupStorageError, MissingBackupObject


def _is_missing(exc):
    code = exc.response.get("Error", {}).get("Code")
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if status is not None and status != 404:
        return False
    return code in {"404", "NoSuchKey", "NotFound"} or (not code and status == 404)


def download_object(
    bucket, key, destination, *, versioned, s3, restorable_headers,
    latest_retained_version,
):
    params = {"Bucket": bucket, "Key": key}
    version_id = ""
    try:
        if versioned:
            try:
                version_id = s3.head_object(**params).get("VersionId") or ""
            except ClientError as exc:
                if not _is_missing(exc):
                    raise
                version_id = latest_retained_version(s3, bucket, key)
                if not version_id:
                    raise MissingBackupObject(
                        f"Storage object {key} has no current or retained version."
                    ) from exc
            if not version_id:
                raise BackupStorageError(
                    f"Version-enabled bucket returned no version id for {key}."
                )
            params["VersionId"] = version_id
        try:
            response = s3.get_object(**params)
        except ClientError as exc:
            # A pinned-version failure is never proof that the final key is absent.
            if not versioned and _is_missing(exc):
                raise MissingBackupObject(f"Storage object {key} is missing.") from exc
            raise
        body = response["Body"]
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with destination.open("wb") as handle:
                while chunk := body.read(1024 * 1024):
                    handle.write(chunk)
                    digest.update(chunk)
            return {
                "key": key,
                "version_id": version_id,
                "size": destination.stat().st_size,
                "sha256": digest.hexdigest(),
                "metadata": response.get("Metadata", {}),
                "content_type": response.get("ContentType", ""),
                "headers": {
                    name: response[name] for name in restorable_headers
                    if name in response and response[name] not in (None, "")
                },
            }
        finally:
            if hasattr(body, "close"):
                body.close()
    except BackupStorageError:
        raise
    except (BotoCoreError, ClientError, OSError) as exc:
        raise BackupStorageError(f"Could not capture storage object {key}.") from exc


def latest_retained_version(s3, bucket, key):
    """Find the newest exact-key data version, including behind a delete marker."""
    key_marker = version_marker = newest = None
    while True:
        params = {"Bucket": bucket, "Prefix": key}
        if key_marker:
            params["KeyMarker"] = key_marker
        if version_marker:
            params["VersionIdMarker"] = version_marker
        page = s3.list_object_versions(**params)
        for item in page.get("Versions", []):
            if item.get("Key") == key and (
                newest is None or item["LastModified"] > newest["LastModified"]
            ):
                newest = item
        if not page.get("IsTruncated"):
            break
        key_marker = page.get("NextKeyMarker")
        version_marker = page.get("NextVersionIdMarker")
    if newest is None:
        return ""
    if not newest.get("VersionId"):
        raise BackupStorageError(f"Retained storage object {key} has no version id.")
    return newest["VersionId"]
