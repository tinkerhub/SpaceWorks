"""Server archive GET regression; the live case proves only opaque byte transport.

Synthetic ciphertext stands in for an encrypted archive: no age decryption,
PostgreSQL restore, or complete archive admission is claimed here.
"""

import hashlib
from io import BytesIO
import os
import socket
from unittest.mock import Mock
from urllib.parse import urlsplit
import uuid

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.response import StreamingBody

from apps.backup import storage


CHUNK_SIZE = 64 * 1024


def test_open_archive_uses_internal_endpoint_and_returns_untouched_stream(
    monkeypatch, settings,
):
    settings.AWS_S3_ENDPOINT_URL = "http://internal-object-store.invalid:9000"
    settings.AWS_S3_PUBLIC_ENDPOINT_URL = "http://unreachable-browser.invalid:9000"
    settings.AWS_STORAGE_BUCKET_NAME = "private-archive-fixture"
    key = "backup-archives/deployment/opaque-fixture.tar.age"
    payload = b"\x00\xffsynthetic encrypted fixture\x80"
    raw = BytesIO(payload)
    body = StreamingBody(raw, len(payload))
    metadata = {"fixture": "opaque-ciphertext"}
    response = {"Body": body, "Metadata": metadata, "ContentLength": len(payload)}
    internal = Mock()
    internal.get_object.return_value = response

    def sdk_client(service, **kwargs):
        assert service == "s3"
        if kwargs["endpoint_url"] == settings.AWS_S3_PUBLIC_ENDPOINT_URL:
            raise EndpointConnectionError(endpoint_url=kwargs["endpoint_url"])
        assert kwargs["endpoint_url"] == settings.AWS_S3_ENDPOINT_URL
        return internal

    # Keep the production endpoint-selection factory; replace only the SDK edge.
    monkeypatch.setattr(storage.boto3, "client", sdk_client)
    try:
        opened = storage.open_archive(key)
        assert opened is body
        assert raw.tell() == 0  # The caller still owns an unread stream.
        internal.get_object.assert_called_once_with(
            Bucket="private-archive-fixture", Key=key,
        )
        assert response["Metadata"] is metadata
        assert response["Metadata"] == {"fixture": "opaque-ciphertext"}
        assert response["ContentLength"] == len(payload)
        assert opened.read(len(payload) + 1) == payload
        assert opened.read(1) == b""
    finally:
        body.close()
    assert raw.closed


def test_open_archive_wraps_botocore_connection_failure(monkeypatch, settings):
    cause = EndpointConnectionError(endpoint_url="http://internal.invalid:9000")
    s3 = Mock()
    s3.get_object.side_effect = cause
    monkeypatch.setattr(storage, "client", Mock(return_value=s3))
    settings.AWS_STORAGE_BUCKET_NAME = "private-archive-fixture"

    with pytest.raises(storage.BackupStorageError) as error:
        storage.open_archive("opaque-fixture.tar.age")

    assert str(error.value) == "The encrypted backup archive could not be opened."
    assert error.value.__cause__ is cause
    s3.get_object.assert_called_once_with(
        Bucket="private-archive-fixture", Key="opaque-fixture.tar.age",
    )


def test_open_archive_wraps_s3_client_failure(monkeypatch, settings):
    cause = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "fixture denied"},
         "ResponseMetadata": {"HTTPStatusCode": 403}},
        "GetObject",
    )
    s3 = Mock()
    s3.get_object.side_effect = cause
    monkeypatch.setattr(storage, "client", Mock(return_value=s3))
    settings.AWS_STORAGE_BUCKET_NAME = "private-archive-fixture"

    with pytest.raises(storage.BackupStorageError) as error:
        storage.open_archive("opaque-fixture.tar.age")

    assert str(error.value) == "The encrypted backup archive could not be opened."
    assert error.value.__cause__ is cause
    s3.get_object.assert_called_once_with(
        Bucket="private-archive-fixture", Key="opaque-fixture.tar.age",
    )


@pytest.fixture
def disposable_archive_bucket(settings):
    """Fail closed without explicit local aliases; never touch an existing bucket."""
    assert os.environ.get("SPACEWORKS_TEST_S3_DISPOSABLE") == "1", (
        "Requires explicit disposable S3 opt-in; no skip or provider fallback."
    )
    endpoint = os.environ["SPACEWORKS_TEST_S3_ENDPOINT_URL"]
    parsed = urlsplit(endpoint)
    assert parsed.scheme == "http" and parsed.port == 59200
    assert parsed.hostname in {"localhost", "127.0.0.1", "host.docker.internal"}
    assert not parsed.username and not parsed.password
    assert parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
    access_key = os.environ["SPACEWORKS_TEST_S3_ACCESS_KEY_ID"]
    secret_key = os.environ["SPACEWORKS_TEST_S3_SECRET_ACCESS_KEY"]
    assert access_key.strip() and secret_key.strip()
    settings.AWS_S3_ENDPOINT_URL = endpoint
    settings.AWS_ACCESS_KEY_ID = access_key
    settings.AWS_SECRET_ACCESS_KEY = secret_key
    settings.AWS_S3_REGION_NAME = "us-east-1"
    settings.AWS_S3_SIGNATURE_VERSION = "s3v4"
    settings.AWS_S3_ADDRESSING_STYLE = "path"
    bucket = "archive-get-stage3-" + uuid.uuid4().hex
    key = "backup-archives/" + uuid.uuid4().hex + ".tar.age"
    settings.AWS_STORAGE_BUCKET_NAME = bucket

    # Bind without listen: nobody can serve HTTP on this reserved loopback port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unreachable:
        unreachable.bind(("127.0.0.1", 0))
        settings.AWS_S3_PUBLIC_ENDPOINT_URL = (
            f"http://127.0.0.1:{unreachable.getsockname()[1]}"
        )
        s3 = storage.client()  # Genuine production boto factory, unchanged Config.
        try:
            assert s3.meta.config.signature_version == "s3v4"
            assert s3.meta.config.request_checksum_calculation == "when_supported"
            assert s3.meta.config.response_checksum_validation == "when_supported"
            s3.create_bucket(Bucket=bucket)
            try:
                s3.put_bucket_versioning(
                    Bucket=bucket, VersioningConfiguration={"Status": "Enabled"},
                )
                assert s3.get_bucket_versioning(Bucket=bucket)["Status"] == "Enabled"
                yield s3, bucket, key
            finally:
                # Only our freshly created bucket, including every owned version
                # and delete marker. Bounded passes refuse incomplete cleanup.
                assert bucket.startswith("archive-get-stage3-")
                for _ in range(3):
                    page = s3.list_object_versions(Bucket=bucket, MaxKeys=1000)
                    objects = [
                        {"Key": item["Key"], "VersionId": item["VersionId"]}
                        for group in (page.get("Versions", []), page.get("DeleteMarkers", []))
                        for item in group
                    ]
                    assert all(item["Key"] == key for item in objects)
                    if not objects:
                        assert not page.get("IsTruncated")
                        break
                    result = s3.delete_objects(
                        Bucket=bucket, Delete={"Objects": objects, "Quiet": True},
                    )
                    assert not result.get("Errors"), "Owned-bucket cleanup failed"
                else:
                    pytest.fail("Owned-bucket version cleanup exceeded its bound")
                s3.delete_bucket(Bucket=bucket)
        finally:
            s3.close()


def test_real_sdk_open_archive_streams_internal_get_with_public_unreachable(
    disposable_archive_bucket,
):
    s3, bucket, key = disposable_archive_bucket
    # Opaque synthetic ciphertext only; intentionally not an age/PG restore fixture.
    payload = bytes(range(256)) * 1025 + b"\x00\xffsynthetic-ciphertext-tail"
    metadata = {"fixture": "opaque-encrypted-bytes"}
    put = s3.put_object(
        Bucket=bucket, Key=key, Body=payload,
        ContentType="application/octet-stream", Metadata=metadata,
    )
    assert put["VersionId"] and put["VersionId"] != "null"

    # Do not patch open_archive, its factory, the SDK, signing, or checksums.
    body = storage.open_archive(key)
    try:
        assert isinstance(body, StreamingBody)
        digest, size = hashlib.sha256(), 0
        for _ in range(len(payload) // CHUNK_SIZE + 2):
            chunk = body.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            assert size <= len(payload), "GET exceeded the fixture's size bound"
            digest.update(chunk)
        else:
            pytest.fail("GET did not reach EOF within the fixture's read bound")
        assert size == len(payload)
        assert digest.hexdigest() == hashlib.sha256(payload).hexdigest()
    finally:
        body.close()
    assert body._raw_stream.closed

    # HEAD checks locator/metadata preservation, not byte integrity (GET above does).
    after = s3.head_object(Bucket=bucket, Key=key)
    assert after["VersionId"] == put["VersionId"]
    assert after["ContentLength"] == len(payload)
    assert after["ContentType"] == "application/octet-stream"
    assert after["Metadata"] == metadata
