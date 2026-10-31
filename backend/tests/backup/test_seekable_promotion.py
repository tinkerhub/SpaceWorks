"""Seekable publication regression; parent executes these tests after source freeze."""

from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from apps.backup import artifact_protocol, reconciliation, services_archives, storage
from apps.backup.models import BackupArchive, BackupArtifactLedger
from tests.backup.seekable_promotion_helpers import (
    CHUNK, SIZE, assert_closed, digest_for, install,
)
from tests.backup.test_promotion_e5 import _prepared


def promote(**overrides):
    facts = {"expected_size": SIZE, "expected_sha256": digest_for(SIZE)} | overrides
    return storage.create_final_from_staging("staging", "final", **facts)


@pytest.mark.parametrize("size", [0, CHUNK, SIZE])
def test_real_streaming_body_spools_private_disk_before_checksum_like_put(monkeypatch, settings, size):
    client, body, records = install(monkeypatch, settings, size=size, length=size)
    promote(expected_size=size, expected_sha256=digest_for(size))
    assert len(client.puts) == 1
    assert client.puts[0]["Body"] is records[0].handle
    assert client.puts[0]["ContentLength"] == size
    assert client.gets == [{"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": "staging"}]
    assert client.puts[0]["Key"] == "final"
    assert sum(records[0].writes) == size
    assert all(amount <= min(CHUNK, size - offset + 1) for offset, amount in body._raw_stream.requests)
    assert not client.deletes
    assert_closed(body, records)


@pytest.mark.parametrize("facts", [
    {"expected_size": SIZE + 1}, {"expected_size": SIZE - 1},
    {"expected_sha256": "0" * 64},
])
def test_size_and_hash_refuse_before_final_put(monkeypatch, settings, facts):
    client, body, records = install(monkeypatch, settings)
    with pytest.raises(storage.BackupVerificationError, match="expected size and sha256"):
        promote(**facts)
    assert not client.puts and not client.deletes
    bound = facts.get("expected_size", SIZE)
    assert sum(records[0].writes) <= bound
    if bound < SIZE:
        assert sum(records[0].writes) == (bound // CHUNK) * CHUNK
    assert all(amount <= min(CHUNK, bound - offset + 1) for offset, amount in body._raw_stream.requests)
    assert_closed(body, records)


@pytest.mark.parametrize("facts", [
    {"expected_size": None}, {"expected_sha256": None}, {"expected_size": True},
    {"expected_size": -1}, {"expected_size": "23"}, {"expected_size": 23.0},
    {"expected_sha256": "A" * 64}, {"expected_sha256": "f" * 63},
    {"expected_sha256": b"f" * 64},
])
def test_malformed_paired_facts_refuse_before_provider(monkeypatch, facts):
    def forbidden():
        pytest.fail("invalid facts reached provider or temporary-file allocation")
    monkeypatch.setattr(storage, "client", forbidden)
    monkeypatch.setattr("apps.backup.storage_promotion.tempfile.TemporaryFile", forbidden)
    with pytest.raises(storage.BackupVerificationError, match="canonical sha256 together"):
        promote(**facts)


@pytest.mark.parametrize("length", [SIZE, "missing", None, True, -1, "23", 23.0])
def test_legacy_two_argument_copy_requires_valid_bounded_get_length(monkeypatch, settings, length):
    client, body, records = install(monkeypatch, settings, length=length)
    if type(length) is int and length >= 0:
        storage.copy_archive("staging", "final")
        assert len(client.puts) == 1
        assert sum(records[0].writes) == SIZE
        assert all(n <= min(CHUNK, SIZE - offset + 1) for offset, n in body._raw_stream.requests)
    else:
        with pytest.raises(storage.BackupStorageError, match="valid content length"):
            storage.copy_archive("staging", "final")
        assert not records and not client.puts
    assert not client.deletes
    assert_closed(body, records)


@pytest.mark.parametrize("failure", ["read", "allocate", "write", "sdk", "409", "412"])
@pytest.mark.parametrize("close_error", [False, True])
def test_primary_failure_survives_close_failures_and_never_deletes_winner(
    monkeypatch, settings, failure, close_error,
):
    primary = OSError("primary I/O failure")
    options = {"close_error": close_error}
    message = "could not be promoted"
    if failure in {"read", "allocate", "write"}:
        options[{"read": "read_error", "allocate": "allocation_error", "write": "write_error"}[failure]] = primary
    elif failure == "sdk":
        primary = EndpointConnectionError(endpoint_url="https://invalid.example")
        options["put_error"] = primary
    else:
        primary = ClientError({"Error": {"Code": "ConditionalRequestConflict" if failure == "409" else "PreconditionFailed"},
                               "ResponseMetadata": {"HTTPStatusCode": int(failure)}}, "PutObject")
        options["put_error"] = primary
        message = "immutable final backup locator already exists"
    client, body, records = install(monkeypatch, settings, **options)
    winner = client.winner
    with pytest.raises(storage.BackupStorageError, match=message) as error:
        promote()
    assert type(error.value) is storage.BackupStorageError
    assert error.value.__cause__ is primary
    assert len(client.puts) == int(failure in {"sdk", "409", "412"})
    assert client.winner == winner and not client.deletes
    assert bool(records) is (failure != "allocate")
    assert_closed(body, records)


def test_verification_subtype_survives_both_close_failures(monkeypatch, settings):
    client, body, records = install(monkeypatch, settings, close_error=True)
    with pytest.raises(storage.BackupVerificationError):
        promote(expected_sha256="0" * 64)
    assert not client.puts and not client.deletes
    assert_closed(body, records)


def test_close_failure_after_success_is_typed_and_both_handles_closed(monkeypatch, settings):
    client, body, records = install(monkeypatch, settings, close_error=True)
    with pytest.raises(storage.BackupStorageError, match="could not be promoted") as error:
        promote()
    assert isinstance(error.value.__cause__, OSError)
    assert len(client.puts) == 1 and not client.deletes
    assert_closed(body, records)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("route", ["protocol", "reconcile"])
@pytest.mark.parametrize("bad_final", [False, True])
def test_real_ledger_paths_forward_facts_and_require_final_readback(
    monkeypatch, tmp_path, route, bad_final,
):
    _space, _recipient, archive, ledger, size, digest = _prepared(tmp_path)
    facts = {"expected_size": size, "expected_sha256": digest}
    events = []

    def verify(key, **kwargs):
        assert kwargs == facts
        archive.refresh_from_db()
        ledger.refresh_from_db()
        assert archive.status != BackupArchive.Status.AVAILABLE
        assert ledger.state != BackupArtifactLedger.State.AVAILABLE
        events.append(("verify", key))
        if bad_final and key == ledger.final_locator:
            raise storage.BackupVerificationError("injected final readback mismatch")
        return size, digest

    def create(staging, final, **kwargs):
        assert (staging, final, kwargs) == (ledger.staging_locator, ledger.final_locator, facts)
        ledger.refresh_from_db()
        assert ledger.state == BackupArtifactLedger.State.STAGING_VERIFIED
        events.append(("create", final))

    monkeypatch.setattr(storage, "stream_verify", verify)
    monkeypatch.setattr(storage, "create_final_from_staging", create)
    monkeypatch.setattr(storage, "upload_staging", lambda *_a: None)
    monkeypatch.setattr(storage, "object_exists", lambda key: key == ledger.staging_locator)
    monkeypatch.setattr(storage, "delete_archive", lambda key: events.append(("delete", key)) or True)
    build = SimpleNamespace(manifest=ledger.outer_manifest,
                            promotion_snapshot=ledger.frozen_promotion_snapshot,
                            archive_sha256=digest, encrypted="not-opened-by-upload-double")

    def run():
        if route == "protocol":
            return artifact_protocol.upload_verify_and_promote(archive, build, size)
        return reconciliation._reconcile_pending(ledger.pk)

    if bad_final:
        with pytest.raises(storage.BackupVerificationError):
            run()
    else:
        run()
    archive.refresh_from_db()
    ledger.refresh_from_db()
    assert (archive.status == BackupArchive.Status.AVAILABLE) is (not bad_final)
    assert ledger.state == (BackupArtifactLedger.State.STAGING_VERIFIED if bad_final
                            else BackupArtifactLedger.State.AVAILABLE)
    assert events[:3] == [("verify", ledger.staging_locator), ("create", ledger.final_locator),
                          ("verify", ledger.final_locator)]
    assert events[3:] == ([] if bad_final else [("delete", ledger.staging_locator)])


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("bad_final", [False, True])
def test_makerspace_runner_forwards_captured_file_facts_before_available(
    monkeypatch, tmp_path, bad_final,
):
    import hashlib
    from apps.makerspaces.models import Makerspace

    space = Makerspace.objects.create(name="Seekable capture", slug="seekable-capture")
    archive = services_archives.create_archive(None, scope=BackupArchive.Scope.MAKERSPACE, makerspace=space)
    encrypted = tmp_path / "synthetic-ciphertext.age"
    encrypted.write_bytes(b"synthetic ciphertext fixture only")
    size, captured_hash = encrypted.stat().st_size, hashlib.sha256()
    with encrypted.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            captured_hash.update(chunk)
    digest = captured_hash.hexdigest()
    cleaned, events = [], []
    build = (encrypted, {"captured": True}, SimpleNamespace(cleanup=lambda: cleaned.append(True)), digest)
    monkeypatch.setattr(services_archives, "build_archive", lambda _archive: build)
    monkeypatch.setattr(storage, "upload_staging", lambda key, path: events.append("upload"))
    monkeypatch.setattr(storage, "delete_archive", lambda _key: True)
    monkeypatch.setattr(storage, "delete_archive_prefix", lambda _prefix: True)

    def verify(key, **kwargs):
        assert kwargs == {"expected_size": size, "expected_sha256": digest}
        assert BackupArchive.objects.get(pk=archive.pk).status != BackupArchive.Status.AVAILABLE
        events.append("verify")
        if bad_final and events.count("verify") == 2:
            raise storage.BackupVerificationError("injected final readback mismatch")
        return size, digest

    def create(staging, final, **kwargs):
        current = BackupArchive.objects.get(pk=archive.pk)
        assert current.status == BackupArchive.Status.PROMOTING
        assert (staging, final) == (current.staging_object_key, current.object_key)
        assert kwargs == {"expected_size": size, "expected_sha256": digest}
        events.append("create")

    monkeypatch.setattr(storage, "stream_verify", verify)
    monkeypatch.setattr(storage, "create_final_from_staging", create)
    result = services_archives.run_archive(archive.pk)
    assert events == ["upload", "verify", "create", "verify"] and cleaned == [True]
    assert result.status == (BackupArchive.Status.FAILED if bad_final else BackupArchive.Status.AVAILABLE)
    if not bad_final:
        assert (result.size_bytes, result.archive_sha256) == (size, digest)
