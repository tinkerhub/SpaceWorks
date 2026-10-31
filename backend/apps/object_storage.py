"""Shared deletion primitives for versioned S3-compatible object stores."""

import logging

from botocore.exceptions import BotoCoreError, ClientError


logger = logging.getLogger(__name__)

UNSUPPORTED_LIST_OBJECT_VERSIONS_ERROR_CODES = frozenset(
    {
        "InvalidRequest",
        "MethodNotAllowed",
        "NotImplemented",
        "UnsupportedOperation",
        "XNotImplemented",
    }
)


def delete_all_versions(client, *, bucket, key, require_version_listing=False):
    """Delete every retained version and delete marker for one exact key.

    The default unsupported-listing fallback is for trusted terminal/restore
    callers controlling key ownership. Ordinary cleanup must instead use
    ``delete_accepted_object_versions``. A proven empty listing is always a no-op.
    """
    params = {"Bucket": bucket, "Prefix": key}
    try:
        first_page = client.list_object_versions(**params)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if (
            code in UNSUPPORTED_LIST_OBJECT_VERSIONS_ERROR_CODES
            and not require_version_listing
        ):
            logger.warning(
                "object_version_listing_failed_falling_back",
                extra={"bucket": bucket, "object_key": key, "error_code": code},
                exc_info=True,
            )
            client.delete_object(Bucket=bucket, Key=key)
            return
        _log_listing_failure(bucket=bucket, key=key)
        raise
    except BotoCoreError:
        _log_listing_failure(bucket=bucket, key=key)
        raise

    try:
        objects = _listed_versions(
            client, bucket=bucket, key=key, first_page=first_page
        )
    except (BotoCoreError, ClientError):
        _log_listing_failure(bucket=bucket, key=key)
        raise

    if not objects:
        return

    for start in range(0, len(objects), 1000):
        response = client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": objects[start : start + 1000], "Quiet": True},
        )
        errors = (response or {}).get("Errors", ())
        if errors:
            first = errors[0]
            raise ClientError(
                {
                    "Error": {
                        "Code": first.get("Code", "DeleteObjectsError"),
                        "Message": first.get("Message", "Object version deletion failed."),
                    }
                },
                "DeleteObjects",
            )


def delete_accepted_object_versions(client, *, bucket, key, report_data_versions=False):
    """Delete only an exact version snapshot while bucket versioning is enabled.

    Gather and validate the entire listing before any deletion. A later import
    promotion gets a new version ID outside this snapshot, including when the
    snapshot is empty. Legacy ``null`` IDs are safe only with current versioning
    enabled; suspended/unversioned stores cannot prove this cleanup safe. Return
    only DATA version IDs, frozen, after every deletion batch succeeds when
    report_data_versions is requested. The default return remains None.
    """
    try:
        versioning = client.get_bucket_versioning(Bucket=bucket)
        if not isinstance(versioning, dict) or versioning.get("Status") != "Enabled":
            raise _cleanup_refused("GetBucketVersioning")
        objects, data_version_ids = _accepted_version_snapshot(client, bucket=bucket, key=key)
        for start in range(0, len(objects), 1000):
            response = client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": list(objects[start : start + 1000]), "Quiet": True},
            )
            if not isinstance(response, dict):
                raise _cleanup_refused("DeleteObjects")
            errors = response.get("Errors", [])
            if not isinstance(errors, list) or errors:
                raise _cleanup_refused("DeleteObjects")
        return data_version_ids if report_data_versions else None
    except (BotoCoreError, ClientError):
        # Provider messages may contain signed URLs or credentials. Keep the
        # wrapper-visible payload and exception chain independent of those bytes.
        raise _cleanup_refused("DeleteAcceptedObjectVersions") from None


def _accepted_version_snapshot(client, *, bucket, key):
    objects, version_ids, data_version_ids, markers = [], set(), set(), set()
    params = {"Bucket": bucket, "Prefix": key}
    while True:
        page = client.list_object_versions(**params)
        if not isinstance(page, dict) or type(page.get("IsTruncated")) is not bool:
            raise _cleanup_refused("ListObjectVersions")
        for name in ("Versions", "DeleteMarkers"):
            group = page.get(name, [])
            if not isinstance(group, list):
                raise _cleanup_refused("ListObjectVersions")
            for item in group:
                if not isinstance(item, dict) or not isinstance(item.get("Key"), str):
                    raise _cleanup_refused("ListObjectVersions")
                if item["Key"] != key:
                    continue
                version_id = item.get("VersionId")
                if (not isinstance(version_id, str) or not version_id.strip()
                        or version_id in version_ids):
                    raise _cleanup_refused("ListObjectVersions")
                version_ids.add(version_id)
                if name == "Versions":
                    data_version_ids.add(version_id)
                objects.append({"Key": key, "VersionId": version_id})
        if not page["IsTruncated"]:
            return tuple(objects), frozenset(data_version_ids)
        marker = (page.get("NextKeyMarker"), page.get("NextVersionIdMarker"))
        if (any(not isinstance(value, str) or not value for value in marker)
                or marker in markers):
            raise _cleanup_refused("ListObjectVersions")
        markers.add(marker)
        params.update(KeyMarker=marker[0], VersionIdMarker=marker[1])


def _cleanup_refused(operation):
    return ClientError(
        {"Error": {"Code": "ObjectCleanupUnconfirmed",
                   "Message": "Version-specific object cleanup could not be confirmed."}},
        operation,
    )


def _listed_versions(client, *, bucket, key, first_page):
    objects = []
    page = first_page
    while True:
        objects.extend(
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for group in (page.get("Versions", ()), page.get("DeleteMarkers", ()))
            for item in group
            if item.get("Key") == key
        )
        if not page.get("IsTruncated"):
            return objects
        params = {
            "Bucket": bucket,
            "Prefix": key,
            "KeyMarker": page.get("NextKeyMarker"),
            "VersionIdMarker": page.get("NextVersionIdMarker"),
        }
        page = client.list_object_versions(
            **{name: value for name, value in params.items() if value is not None}
        )


def _log_listing_failure(*, bucket, key):
    logger.error(
        "object_version_listing_failed_propagating",
        extra={"bucket": bucket, "object_key": key},
        exc_info=True,
    )
