"""Outside-DB metadata survives source RUNNING rows and a large all-table report."""

from copy import deepcopy
from datetime import timedelta
import json
import stat
import uuid

import pytest
from django.db import InternalError, transaction
from django.utils import timezone

from apps.backup import restore_control_records, storage
from apps.backup.full_control_record import capture_archive_record, validate_archive_record
from apps.backup.full_restore_identity import MAX_CONTROL_BYTES, read_private_control
from apps.backup.models import BackupArchive, DeploymentRecoveryState, RestoreOperation
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from tests.backup.full_backup_fixture_helpers import make_full_fixture, sha, sign_manifest


pytestmark = pytest.mark.django_db(transaction=True)


def selected_restore(tmp_path):
    identifier = uuid.uuid4()
    fixture = make_full_fixture(tmp_path, archive_id=identifier)
    now = timezone.now()
    archive = BackupArchive.objects.create(
        id=identifier, scope="deployment", status="available", manifest=fixture.manifest,
        object_key=f"backup-archives/deployment/{identifier}.tar.age",
        archive_sha256=sha(fixture.encrypted.read_bytes()), size_bytes=fixture.encrypted.stat().st_size,
        completed_at=now, expires_at=now + timedelta(days=30), age_encrypted=True,
        download_token_digest="f" * 64, download_token_expires_at=now + timedelta(minutes=2),
    )
    restore = RestoreOperation.objects.create(archive=archive, kind="disaster", stage="quiesced",
                                             restore_diff={"report": "r" * (MAX_CONTROL_BYTES + 1)})
    DeploymentDatabaseIdentity.load()
    return fixture, archive, restore


def test_large_report_has_separate_private_fsynced_bounded_identity_companion(tmp_path, monkeypatch):
    fixture, archive, restore = selected_restore(tmp_path)
    fsyncs = []
    import os

    real_fsync = os.fsync

    def fsync(fd):
        fsyncs.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr("apps.backup.full_control_record.os.fsync", fsync)
    output = tmp_path / "control.json"
    restore_control_records.export_control_record(restore.pk, output)
    companion = output.with_name(output.name + ".identity.json")
    assert output.stat().st_size > MAX_CONTROL_BYTES
    assert companion.stat().st_size <= MAX_CONTROL_BYTES
    for path in (output, companion):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with companion.open() as stream:
        identity = read_private_control(stream)
    payload = json.loads(output.read_text())
    assert identity == {"full_target_identity": payload["full_target_identity"]}
    assert payload["full_archive_identity"] == capture_archive_record(archive)
    assert len(fsyncs) == 2


@pytest.mark.parametrize("change", ["id", "manifest", "sha", "size", "bool-size", "key", "dates", "missing"])
def test_selected_archive_control_facts_refuse_tamper(tmp_path, change):
    fixture, archive, _restore = selected_restore(tmp_path)
    record, manifest = capture_archive_record(archive), deepcopy(fixture.manifest)
    if change == "id":
        record["archive_id"] = str(uuid.uuid4())
    elif change == "manifest":
        # Another valid signature for this ID still cannot replace the selected manifest.
        manifest["purge_warning"] += " changed but valid"
        manifest = sign_manifest(manifest)
    elif change == "sha":
        record["archive_sha256"] = ""
    elif change in {"size", "bool-size"}:
        record["size_bytes"] = True if change == "bool-size" else 0
    elif change == "key":
        record["object_key"] = "other-archive.tar.age"
    elif change == "dates":
        record["expires_at"] = record["completed_at"]
    else:
        record.pop("manifest_sha256")
    with pytest.raises(RuntimeError, match="selected signed-full"):
        validate_archive_record(record, manifest, archive.pk)


@pytest.mark.parametrize("source_state", ["fresh-snapshot-null-expiry", "already-retained-same-expiry"])
def test_rehydrate_restores_available_metadata_and_second_export_is_valid(tmp_path, monkeypatch, source_state):
    fixture, archive, restore = selected_restore(tmp_path)
    archive_id, restore_id = archive.pk, restore.pk
    output = restore_control_records.export_control_record(restore_id, tmp_path / "control.json")
    control_bytes = output.read_bytes()
    control = json.loads(control_bytes)
    expected = capture_archive_record(archive)
    with transaction.atomic():
        with pytest.raises(InternalError, match="immutable backup archive expiry"), transaction.atomic():
            BackupArchive.objects.filter(pk=archive.pk).update(expires_at=None)
    archive.refresh_from_db()
    assert capture_archive_record(archive) == expected
    if source_state == "fresh-snapshot-null-expiry":
        # SQL-row replacement simulation, not pg_restore evidence. The simple
        # operation protects its archive, so delete it first; no rollback evidence exists.
        assert not restore.rollback_objects.exists()
        RestoreOperation.objects.filter(pk=restore_id).delete()
        BackupArchive.objects.filter(pk=archive_id).delete()
        assert not RestoreOperation.objects.filter(pk=restore_id).exists()
        assert not BackupArchive.objects.filter(pk=archive_id).exists()
        # create_archive leaves expiry NULL; promotion assigns it after capture.
        archive = BackupArchive.objects.create(
            id=archive_id, scope="deployment", status="running", expires_at=None,
            object_key=expected["object_key"], manifest={}, archive_sha256="",
            size_bytes=0, completed_at=None,
        )
        archive.refresh_from_db()
        assert archive.expires_at is None
    else:
        # Compatibility: an already-retained row keeps the same immutable expiry.
        BackupArchive.objects.filter(pk=archive_id).update(status="running", manifest={}, archive_sha256="",
                                                         size_bytes=0, completed_at=None)
        archive.refresh_from_db()
        assert archive.expires_at.isoformat() == expected["expires_at"]
    assert archive.pk == archive_id
    assert archive.status == "running"
    assert archive.manifest == {}
    assert archive.archive_sha256 == ""
    assert archive.size_bytes == 0
    assert archive.completed_at is None
    assert output.read_bytes() == control_bytes
    monkeypatch.setattr(storage, "delete_archive_prefix", lambda _prefix: True)
    result = restore_control_records.rehydrate_control_record(restore_id, {
        "control_record": output, "manifest": fixture.manifest_file,
        "archive_id": str(archive_id), "kind": "disaster",
    })
    assert result.pk == restore_id
    result.refresh_from_db()
    assert result.archive_id == archive_id
    assert result.stage == "db_restoring"
    assert RestoreOperation.objects.get(pk=restore_id).restore_diff == control["restore_diff"]
    archive.refresh_from_db()
    assert archive.status == "available"
    assert capture_archive_record(archive) == expected
    assert archive.download_token_digest == ""
    assert archive.download_token_expires_at is None
    assert archive.download_token_consumed_at is None
    second = restore_control_records.export_control_record(result.pk, tmp_path / "control-again.json")
    assert json.loads(second.read_text())["full_archive_identity"] == expected
    assert json.loads(second.read_text())["full_target_identity"] == control["full_target_identity"]


@pytest.mark.parametrize("change", ["different-valid-manifest", "selected-id"])
def test_rehydrate_refuses_changed_input_before_database_rows_or_recovery_state(tmp_path, change):
    fixture, archive, restore = selected_restore(tmp_path)
    output = restore_control_records.export_control_record(restore.pk, tmp_path / "control.json")
    before = BackupArchive.objects.values().get(pk=archive.pk)
    state = DeploymentRecoveryState.objects.values().get()
    selected_id = str(archive.pk)
    if change == "different-valid-manifest":
        fixture.manifest["purge_warning"] += " changed input"
        fixture.manifest = sign_manifest(fixture.manifest)
        fixture.write()
    else:
        selected_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError, match="selected signed-full"):
        restore_control_records.rehydrate_control_record(restore.pk, {
            "control_record": output, "manifest": fixture.manifest_file,
            "archive_id": selected_id, "kind": "disaster",
        })
    assert BackupArchive.objects.values().get(pk=archive.pk) == before
    assert DeploymentRecoveryState.objects.values().get() == state
