"""Separate live S3 lane: unique disposable bucket, real streamed GET/history.

Needs the parent's local MinIO credentials/endpoint and explicit disposable opt-in.
Only this test's unique bucket is cleaned. Never points at implicit AWS defaults.
"""

from contextlib import contextmanager
import os
import uuid

import pytest

from apps.backup import storage
from apps.backup.object_restore_versions import ObjectRestoreError
from apps.backup.restore_object_proof import stream_readback
from apps.object_storage import delete_all_versions
from tests.backup.recovery_object_support import object_fact


@contextmanager
def live_bucket(settings):
    assert os.environ.get("SPACEWORKS_TEST_S3_DISPOSABLE") == "1", (
        "Set SPACEWORKS_TEST_S3_DISPOSABLE=1 only with the parent's dedicated local MinIO endpoint/credentials."
    )
    assert settings.AWS_S3_ENDPOINT_URL, "An explicit disposable S3 endpoint is required; no implicit AWS endpoint."
    s3 = storage.client()
    bucket = "recovery-stage3-" + uuid.uuid4().hex
    s3.create_bucket(Bucket=bucket)
    settings.AWS_STORAGE_BUCKET_NAME = bucket
    try:
        yield s3, bucket
    finally:
        # Every key below is created in our unique bucket; no shared prefix purge.
        for key in ("source", "expired", "staging/expired"):
            delete_all_versions(s3, bucket=bucket, key=key)
        s3.delete_bucket(Bucket=bucket)


def test_real_s3_readback_proves_bytes_size_metadata_type_and_required_header(settings):
    payload = b"actual-streamed-s3-proof" * 100000
    fact = object_fact("source", payload)
    with live_bucket(settings) as (s3, bucket):
        def put(raw, **overrides):
            s3.put_object(Bucket=bucket, Key="source", Body=raw,
                **({"Metadata": fact["metadata"], "ContentType": fact["content_type"], "CacheControl": "private"} | overrides))
        put(payload)
        stream_readback(fact)
        for changed, overrides in [(b"X" * len(payload), {}), (payload + b"x", {}),
            (payload, {"Metadata": {"wrong": "owner"}}), (payload, {"ContentType": "text/plain"}),
            (payload, {"CacheControl": "public"})]:
            put(changed, **overrides)
            with pytest.raises(ObjectRestoreError):
                stream_readback(fact)


@pytest.mark.parametrize("key", ["expired", "staging/expired"])
def test_real_s3_delete_marker_does_not_hide_retained_expired_bytes(settings, key):
    with live_bucket(settings) as (s3, bucket):
        s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        assert s3.get_bucket_versioning(Bucket=bucket)["Status"] == "Enabled"
        s3.put_object(Bucket=bucket, Key=key, Body=b"retained terminal bytes")
        s3.delete_object(Bucket=bucket, Key=key)
        with pytest.raises(storage.BackupStorageError, match="retained versions"):
            storage.assert_object_absent(bucket, key)
        delete_all_versions(s3, bucket=bucket, key=key)
        storage.assert_object_absent(bucket, key)
