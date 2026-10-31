"""Strict version enumeration/deletion; unsupported safety proofs always refuse."""

import boto3
from botocore.client import Config
from django.conf import settings
from django.core.exceptions import ValidationError


class PurgeStorageRefused(ValidationError):
    pass


def client():
    return boto3.client(
        "s3", endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(
            signature_version=settings.AWS_S3_SIGNATURE_VERSION,
            s3={"addressing_style": settings.AWS_S3_ADDRESSING_STYLE},
            connect_timeout=5, read_timeout=20, retries={"total_max_attempts": 1},
        ),
    )


def bucket_name(kind):
    buckets = {"private": settings.AWS_STORAGE_BUCKET_NAME,
               "public_image": settings.PUBLIC_IMAGE_BUCKET}
    if kind not in buckets or not buckets[kind]:
        raise PurgeStorageRefused("Unsupported purge bucket identity.")
    return buckets[kind]


def list_versions(s3, bucket, prefix):
    """Materialize an exact paginated proof, including historical delete markers."""
    result, seen, markers = [], set(), set()
    params = {"Bucket": bucket, "Prefix": prefix}
    try:
        for _ in range(10000):
            page = s3.list_object_versions(**params)
            if type(page.get("IsTruncated")) is not bool:
                raise PurgeStorageRefused("Storage returned an incomplete version listing.")
            for field in ("Versions", "DeleteMarkers"):
                entries = page.get(field, [])
                if not isinstance(entries, list):
                    raise PurgeStorageRefused("Storage version listing is malformed.")
                for item in entries:
                    key, version = item.get("Key"), item.get("VersionId")
                    if (not isinstance(key, str) or not key.startswith(prefix)
                            or not isinstance(version, str) or not version):
                        raise PurgeStorageRefused("Storage did not return exact version identities.")
                    identity = (key, version)
                    if identity in seen:
                        raise PurgeStorageRefused("Storage repeated a version identity.")
                    seen.add(identity)
                    result.append({"Key": key, "VersionId": version})
            if not page["IsTruncated"]:
                return result
            marker = (page.get("NextKeyMarker"), page.get("NextVersionIdMarker"))
            if (not isinstance(marker[0], str) or not marker[0]
                    or marker in markers):
                raise PurgeStorageRefused("Storage version pagination cannot be proven complete.")
            markers.add(marker)
            params = {"Bucket": bucket, "Prefix": prefix, "KeyMarker": marker[0]}
            if marker[1] is not None:
                if not isinstance(marker[1], str) or not marker[1]:
                    raise PurgeStorageRefused("Storage returned an invalid version marker.")
                params["VersionIdMarker"] = marker[1]
        raise PurgeStorageRefused("Storage listing exceeded the bounded purge limit.")
    except PurgeStorageRefused:
        raise
    except Exception as exc:
        raise PurgeStorageRefused("Storage cannot prove a complete version listing.") from exc


def delete_and_verify(s3, closure, verify_boundary):
    # Enumerate EVERY key before touching ANY bytes. No bare DeleteObject fallback.
    versions = {}
    for kind, key in sorted(closure):
        verify_boundary()
        bucket = bucket_name(kind)
        identity = (bucket, key)
        if identity not in versions:
            versions[identity] = [
                row for row in list_versions(s3, bucket, key) if row["Key"] == key
            ]
    try:
        for (bucket, _key), rows in versions.items():
            for offset in range(0, len(rows), 1000):
                verify_boundary()
                batch = rows[offset:offset + 1000]
                response = s3.delete_objects(
                    Bucket=bucket, Delete={"Objects": batch, "Quiet": False},
                )
                if response.get("Errors"):
                    raise PurgeStorageRefused("Storage refused one or more version deletions.")
                deleted = {(row.get("Key"), row.get("VersionId"))
                           for row in response.get("Deleted", [])}
                if deleted != {(row["Key"], row["VersionId"]) for row in batch}:
                    raise PurgeStorageRefused("Storage did not acknowledge every exact version deletion.")
        for bucket, key in versions:
            verify_boundary()
            if any(row["Key"] == key for row in list_versions(s3, bucket, key)):
                raise PurgeStorageRefused("Storage still contains a purge object version or delete marker.")
    except PurgeStorageRefused:
        raise
    except Exception as exc:
        raise PurgeStorageRefused("Storage deletion/readback failed; completion is unconfirmed.") from exc
