"""Only proven object absence permits backup capture to read staging bytes."""

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
from unittest.mock import Mock, call

from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError
import pytest

from apps.backup import storage


BUCKET = "capture-public"
KEY = "event-series/17/cover.png"
STAGED = f"staging/{KEY}"
DATA = b"uploaded cover bytes"


def error(code="NoSuchKey", status=404, operation="GetObject"):
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        operation,
    )


def response():
    return {
        "Body": BytesIO(DATA),
        "Metadata": {"original-name": "cover.png"},
        "ContentType": "image/png",
        "CacheControl": "public, max-age=3600",
        "ContentDisposition": 'inline; filename="cover.png"',
        "ContentEncoding": "identity",
        "ContentLanguage": "en",
        "Expires": datetime(2027, 1, 1, tzinfo=timezone.utc),
        "WebsiteRedirectLocation": "/cover.png",
        "ETag": "not-a-content-digest",
        "VersionId": "response-version-is-not-the-pin",
    }


@pytest.fixture
def s3(monkeypatch):
    fake = Mock(spec=["head_object", "list_object_versions", "get_object"])
    for method in (fake.head_object, fake.list_object_versions, fake.get_object):
        method.side_effect = AssertionError("Unexpected storage call")
    monkeypatch.setattr(storage, "client", lambda: fake)
    return fake


def assert_capture(item, destination, source, *, version_id=""):
    assert destination.read_bytes() == DATA
    assert item == {
        "key": KEY,
        "version_id": version_id,
        "size": len(DATA),
        "sha256": hashlib.sha256(DATA).hexdigest(),
        "metadata": source["Metadata"],
        "content_type": "image/png",
        "headers": {name: source[name] for name in (
            "CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage",
            "ContentType", "Expires", "WebsiteRedirectLocation",
        )},
    }
    assert source["Body"].closed


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(error("AccessDenied", 403), id="forbidden"),
        pytest.param(error("InternalError", 500), id="server-error"),
        pytest.param(
            EndpointConnectionError(endpoint_url="https://storage.invalid"), id="network"
        ),
        pytest.param(BotoCoreError(), id="botocore"),
        pytest.param(error("NoSuchBucket"), id="missing-bucket"),
    ],
)
def test_unversioned_failure_never_reads_valid_staging(s3, tmp_path, failure):
    # Valid staging is available; falling back would silently turn failure into success.
    s3.get_object.side_effect = [failure, response()]

    with pytest.raises(storage.BackupStorageError):
        storage.download_object(BUCKET, KEY, tmp_path / "capture", versioned=False)

    assert s3.mock_calls == [call.get_object(Bucket=BUCKET, Key=KEY)]


def test_stream_read_failure_never_reads_valid_staging(s3, tmp_path):
    body = Mock(spec=["read", "close"])
    body.read.side_effect = [b"partial bytes", OSError("stream interrupted")]
    s3.get_object.side_effect = [{"Body": body}, response()]

    with pytest.raises(storage.BackupStorageError):
        storage.download_object(BUCKET, KEY, tmp_path / "capture", versioned=False)

    assert s3.mock_calls == [call.get_object(Bucket=BUCKET, Key=KEY)]
    body.close.assert_called_once_with()


def test_unversioned_missing_final_captures_staging_under_logical_final_key(s3, tmp_path):
    source = response()
    s3.get_object.side_effect = [error(), source]
    destination = tmp_path / "nested" / "capture"

    item = storage.download_object(BUCKET, KEY, destination, versioned=False)

    assert s3.mock_calls == [
        call.get_object(Bucket=BUCKET, Key=KEY),
        call.get_object(Bucket=BUCKET, Key=STAGED),
    ]
    assert_capture(item, destination, source)


def test_missing_final_and_staging_refuse_capture(s3, tmp_path):
    s3.get_object.side_effect = [error(), error()]
    destination = tmp_path / "capture"

    with pytest.raises(storage.BackupStorageError):
        storage.download_object(BUCKET, KEY, destination, versioned=False)

    assert s3.mock_calls == [
        call.get_object(Bucket=BUCKET, Key=KEY),
        call.get_object(Bucket=BUCKET, Key=STAGED),
    ]
    assert not destination.exists()


@pytest.mark.parametrize("missing", [False, True], ids=["present", "missing"])
def test_already_staging_key_never_adds_another_staging_prefix(s3, tmp_path, missing):
    s3.get_object.side_effect = [error() if missing else response()]
    destination = tmp_path / "capture"

    if missing:
        with pytest.raises(storage.BackupStorageError):
            storage.download_object(BUCKET, STAGED, destination, versioned=False)
    else:
        item = storage.download_object(BUCKET, STAGED, destination, versioned=False)
        assert item["key"] == STAGED
        assert destination.read_bytes() == DATA

    assert s3.mock_calls == [call.get_object(Bucket=BUCKET, Key=STAGED)]


def test_versioned_missing_head_pins_newest_exact_retained_key_behind_marker(s3, tmp_path):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    s3.head_object.side_effect = [error(operation="HeadObject")]
    s3.list_object_versions.side_effect = [{
        "DeleteMarkers": [{"Key": KEY, "VersionId": "marker", "IsLatest": True}],
        "Versions": [
            {"Key": KEY, "VersionId": "old", "LastModified": now - timedelta(days=1)},
            {"Key": KEY + ".extra", "VersionId": "neighbor", "LastModified": now},
        ],
        "IsTruncated": True,
        "NextKeyMarker": KEY,
        "NextVersionIdMarker": "old",
    }, {
        "Versions": [{"Key": KEY, "VersionId": "retained", "LastModified": now}],
        "IsTruncated": False,
    }]
    source = response()
    s3.get_object.side_effect = [source]
    destination = tmp_path / "capture"

    item = storage.download_object(BUCKET, KEY, destination, versioned=True)

    assert s3.mock_calls == [
        call.head_object(Bucket=BUCKET, Key=KEY),
        call.list_object_versions(Bucket=BUCKET, Prefix=KEY),
        call.list_object_versions(
            Bucket=BUCKET, Prefix=KEY, KeyMarker=KEY, VersionIdMarker="old"
        ),
        call.get_object(Bucket=BUCKET, Key=KEY, VersionId="retained"),
    ]
    assert_capture(item, destination, source, version_id="retained")


def test_versioned_missing_final_without_retained_versions_captures_pinned_staging(
    s3, tmp_path
):
    s3.head_object.side_effect = [error(operation="HeadObject"), {"VersionId": "staged-v1"}]
    s3.list_object_versions.side_effect = [{"Versions": [], "IsTruncated": False}]
    source = response()
    s3.get_object.side_effect = [source]
    destination = tmp_path / "capture"

    item = storage.download_object(BUCKET, KEY, destination, versioned=True)

    assert s3.mock_calls == [
        call.head_object(Bucket=BUCKET, Key=KEY),
        call.list_object_versions(Bucket=BUCKET, Prefix=KEY),
        call.head_object(Bucket=BUCKET, Key=STAGED),
        call.get_object(Bucket=BUCKET, Key=STAGED, VersionId="staged-v1"),
    ]
    assert_capture(item, destination, source, version_id="staged-v1")


def test_versioned_successful_head_without_version_id_refuses_staging(s3, tmp_path):
    s3.head_object.side_effect = [{}]

    with pytest.raises(storage.BackupStorageError):
        storage.download_object(BUCKET, KEY, tmp_path / "capture", versioned=True)

    assert s3.mock_calls == [call.head_object(Bucket=BUCKET, Key=KEY)]


def test_versioned_missing_bucket_head_does_not_consult_versions_or_staging(s3, tmp_path):
    s3.head_object.side_effect = [error("NoSuchBucket", operation="HeadObject")]

    with pytest.raises(storage.BackupStorageError):
        storage.download_object(BUCKET, KEY, tmp_path / "capture", versioned=True)

    assert s3.mock_calls == [call.head_object(Bucket=BUCKET, Key=KEY)]


@pytest.mark.parametrize("failure", [
    pytest.param(error("AccessDenied", 403, "ListObjectVersions"), id="forbidden"),
    pytest.param(BotoCoreError(), id="botocore"),
])
def test_version_list_failure_refuses_staging(s3, tmp_path, failure):
    s3.head_object.side_effect = [error(operation="HeadObject")]
    s3.list_object_versions.side_effect = [failure]

    with pytest.raises(storage.BackupStorageError):
        storage.download_object(BUCKET, KEY, tmp_path / "capture", versioned=True)

    assert s3.mock_calls == [
        call.head_object(Bucket=BUCKET, Key=KEY),
        call.list_object_versions(Bucket=BUCKET, Prefix=KEY),
    ]


@pytest.mark.parametrize("pin_source", ["head", "retained"])
def test_missing_pinned_version_refuses_staging(s3, tmp_path, pin_source):
    expected = [call.head_object(Bucket=BUCKET, Key=KEY)]
    if pin_source == "retained":
        s3.head_object.side_effect = [error(operation="HeadObject")]
        s3.list_object_versions.side_effect = [{"Versions": [{
            "Key": KEY, "VersionId": "pinned",
            "LastModified": datetime(2026, 10, 1, tzinfo=timezone.utc),
        }], "IsTruncated": False}]
        expected.append(call.list_object_versions(Bucket=BUCKET, Prefix=KEY))
    else:
        s3.head_object.side_effect = [{"VersionId": "pinned"}]
    s3.get_object.side_effect = [error("NoSuchVersion"), response()]

    with pytest.raises(storage.BackupStorageError):
        storage.download_object(BUCKET, KEY, tmp_path / "capture", versioned=True)

    assert s3.mock_calls == [
        *expected, call.get_object(Bucket=BUCKET, Key=KEY, VersionId="pinned"),
    ]
