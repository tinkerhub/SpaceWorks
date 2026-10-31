"""Explicit opt-in, primitive-only real SDK publication; no PostgreSQL/age proof."""

from contextlib import contextmanager
import hashlib
import os
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody

from apps.backup import storage
from tests.backup.seekable_promotion_helpers import observe_temporaries


LIVE_CHUNK = 64 * 1024


@contextmanager
def owned_bucket(settings):
    assert os.environ.get("SPACEWORKS_TEST_S3_DISPOSABLE") == "1", "Requires explicit disposable S3 opt-in"
    endpoint = os.environ["SPACEWORKS_TEST_S3_ENDPOINT_URL"]
    parsed = urlsplit(endpoint)
    assert parsed.scheme == "http" and parsed.port == 59200
    assert parsed.hostname in {"localhost", "127.0.0.1", "host.docker.internal"}
    assert not parsed.username and not parsed.password and parsed.path in {"", "/"}
    assert not parsed.query and not parsed.fragment
    settings.AWS_S3_ENDPOINT_URL = endpoint
    settings.AWS_ACCESS_KEY_ID = os.environ["SPACEWORKS_TEST_S3_ACCESS_KEY_ID"]
    settings.AWS_SECRET_ACCESS_KEY = os.environ["SPACEWORKS_TEST_S3_SECRET_ACCESS_KEY"]
    assert settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY
    settings.AWS_S3_REGION_NAME = "us-east-1"
    settings.AWS_S3_SIGNATURE_VERSION = "s3v4"
    settings.AWS_S3_ADDRESSING_STYLE = "path"
    # Production factory: request/response checksum configuration is untouched.
    client = storage.client()
    assert client.meta.config.request_checksum_calculation == "when_supported"
    bucket = "seekable-stage3-" + uuid.uuid4().hex
    settings.AWS_STORAGE_BUCKET_NAME = bucket
    client.create_bucket(Bucket=bucket)
    try:
        client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        assert client.get_bucket_versioning(Bucket=bucket)["Status"] == "Enabled"
        yield client, bucket
    finally:
        # Whole-bucket cleanup is safe only because this test just created it.
        assert bucket.startswith("seekable-stage3-")
        while True:
            page = client.list_object_versions(Bucket=bucket, MaxKeys=1000)
            objects = [{"Key": item["Key"], "VersionId": item["VersionId"]}
                       for group in (page.get("Versions", []), page.get("DeleteMarkers", []))
                       for item in group]
            if not objects:
                break
            response = client.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
            assert not response.get("Errors"), "Owned-bucket version cleanup failed"
        client.delete_bucket(Bucket=bucket)


class ObservingClient:
    """Observe real handles; delegate GET/PUT unchanged to the genuine client."""

    def __init__(self, client):
        self.client, self.sources, self.puts = client, [], []

    def get_object(self, **kwargs):
        response = self.client.get_object(**kwargs)
        body = response["Body"]
        assert isinstance(body, StreamingBody) and not body.seekable()
        record = SimpleNamespace(body=body, closes=0)
        self.sources.append(record)
        original_close = body.close

        def close():
            record.closes += 1
            return original_close()

        body.close = close
        return response

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        body = kwargs["Body"]
        assert body.seekable() and body.tell() == 0
        assert body.fileno() >= 0
        assert kwargs["IfNoneMatch"] == "*"
        assert kwargs["ContentType"] == "application/octet-stream"
        # Do not consume, replace or alter Body/checksums/conditional headers.
        return self.client.put_object(**kwargs)

    def delete_object(self, **kwargs):
        raise AssertionError("Promotion must not delete provider bytes")


def assert_handles_closed(observed, records):
    assert observed.sources and records
    assert all(record.closes == 1 and record.body._raw_stream.closed for record in observed.sources)
    assert all(record.close_attempts == 1 and record.handle.closed for record in records)
    for record in records:
        with pytest.raises(ValueError):
            record.handle.fileno()


def full_get(client, bucket, key):
    response = client.get_object(Bucket=bucket, Key=key)
    digest, size = hashlib.sha256(), 0
    try:
        while chunk := response["Body"].read(LIVE_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    finally:
        response["Body"].close()
    assert size == response["ContentLength"]
    return size, digest.hexdigest(), response.get("VersionId")


def upload_synthetic(client, bucket, tmp_path):
    path = tmp_path / "synthetic-ciphertext.age"
    digest, size = hashlib.sha256(), 0
    with path.open("wb") as handle:
        for index in range(19):
            chunk = bytes([index]) * (LIVE_CHUNK - index)
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    with path.open("rb") as handle:
        client.put_object(Bucket=bucket, Key="staging", Body=handle, ContentLength=size)
    return size, digest.hexdigest()


def observe(monkeypatch, client):
    # Larger live chunks keep this primitive test finite; no checksum overrides.
    records = observe_temporaries(monkeypatch, chunk_size=LIVE_CHUNK)
    observed = ObservingClient(client)
    monkeypatch.setattr(storage, "client", lambda: observed)
    return observed, records


def test_real_sdk_seekable_publication_and_conditional_winner_preservation(monkeypatch, settings, tmp_path):
    with owned_bucket(settings) as (client, bucket):
        size, digest = upload_synthetic(client, bucket, tmp_path)
        staging_before = full_get(client, bucket, "staging")
        observed, records = observe(monkeypatch, client)
        storage.create_final_from_staging("staging", "final", expected_size=size, expected_sha256=digest)
        assert full_get(client, bucket, "final")[:2] == (size, digest)
        assert full_get(client, bucket, "staging") == staging_before
        assert observed.puts[0]["Body"] is records[0].handle
        assert observed.puts[0]["ContentLength"] == size
        assert_handles_closed(observed, records)

        # A separate actual PUT owns this locator before promotion attempts it.
        winner_bytes = b"synthetic independent winner"
        winner = client.put_object(Bucket=bucket, Key="winner", Body=winner_bytes)
        before = full_get(client, bucket, "winner")
        with pytest.raises(storage.BackupStorageError, match="immutable final backup locator already exists") as error:
            storage.create_final_from_staging("staging", "winner", expected_size=size, expected_sha256=digest)
        assert isinstance(error.value.__cause__, ClientError)
        assert error.value.__cause__.response["ResponseMetadata"]["HTTPStatusCode"] in {409, 412}
        assert full_get(client, bucket, "winner") == before
        assert before == (len(winner_bytes), hashlib.sha256(winner_bytes).hexdigest(), winner["VersionId"])
        assert full_get(client, bucket, "staging") == staging_before
        versions = client.list_object_versions(Bucket=bucket)
        assert [item["VersionId"] for item in versions["Versions"] if item["Key"] == "winner"] == [winner["VersionId"]]
        assert not versions.get("DeleteMarkers")
        assert len(observed.puts) == 2
        assert_handles_closed(observed, records)


@pytest.mark.parametrize("mismatch", ["undersize", "oversize", "sha256"])
def test_real_sdk_mismatch_refuses_before_final_write(monkeypatch, settings, tmp_path, mismatch):
    with owned_bucket(settings) as (client, bucket):
        size, digest = upload_synthetic(client, bucket, tmp_path)
        before = full_get(client, bucket, "staging")
        expected_size = size + {"undersize": 1, "oversize": -1, "sha256": 0}[mismatch]
        expected_sha256 = "0" * 64 if mismatch == "sha256" else digest
        observed, records = observe(monkeypatch, client)
        with pytest.raises(storage.BackupVerificationError):
            storage.create_final_from_staging("staging", "final", expected_size=expected_size,
                                              expected_sha256=expected_sha256)
        assert not observed.puts
        assert_handles_closed(observed, records)
        assert full_get(client, bucket, "staging") == before
        with pytest.raises(ClientError) as error:
            client.get_object(Bucket=bucket, Key="final")
        assert error.value.response["Error"]["Code"] == "NoSuchKey"
        versions = client.list_object_versions(Bucket=bucket)
        assert all(item["Key"] == "staging" for item in versions.get("Versions", []))
        assert not versions.get("DeleteMarkers")
