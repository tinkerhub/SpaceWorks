"""Real SQL ownership/journal proofs with synthetic S3 wire; no signature claim."""

from datetime import timedelta
import json

import pytest
from django.utils import timezone

from apps.backup import storage
from apps.backup.full_format import FULL_FORMAT
from apps.backup.host_marker import MarkerState, marker_payload, read_marker, write_marker_fsynced
from apps.backup.models import RestoreOperation, RestoreRollbackObject
from apps.backup.object_restore_versions import ObjectRestoreError
from apps.backup.restore_journal_proof import recovery_references
from apps.backup.restore_object_apply import restore_objects
from apps.backup.restore_object_proof import manifest_objects, verify_restored_objects, verify_source_closure
from tests.backup.recovery_object_support import ObjectWire, object_fact
from tests.backup.recovery_test_support import ARTIFACT, RESTORE_ID, archive_row, marker_rig


pytestmark = pytest.mark.django_db(transaction=True)


def source_fixture(rig, settings, monkeypatch, tmp_path):
    old_archive = archive_row()
    old_restore = RestoreOperation.objects.create(archive=old_archive, kind="disaster")
    key = "rollback/" + str(old_restore.pk) + "/private/original.jpg"
    RestoreRollbackObject.objects.create(restore=old_restore, bucket_kind="private", source_key="original.jpg",
        copy_key=key, expires_at=timezone.now() + timedelta(days=7))
    payload = b"authenticated archived rollback copy bytes"
    fact = object_fact(key, payload)
    manifest = {"format": FULL_FORMAT, "capture_id": rig.operation.capture_id, "storage": {"objects": [fact]}}
    archive = archive_row(manifest=manifest, archive_sha256=ARTIFACT)
    restore = RestoreOperation.objects.create(id=RESTORE_ID, archive=archive, kind="disaster", stage="objects_restoring")
    settings.SPACEWORKS_HOST_MARKER_PATH = str(rig.marker)
    write_marker_fsynced(rig.marker, marker_payload(MarkerState.RESTORE_BLOCKED, rig.identity, operation=rig.operation))
    wire = ObjectWire()
    wire.put(key, b"target pre-replacement rollback copy")
    monkeypatch.setattr(storage, "client", lambda: wire)
    source = tmp_path / "bundle/objects/private" / key
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    return restore, manifest, wire, tmp_path / "bundle", tmp_path / "journal.jsonl"


def test_archived_rollback_ref_is_source_checked_then_only_current_exact_journal_copy_exempt(tmp_path, settings, monkeypatch):
    with marker_rig(tmp_path) as rig:
        restore, manifest, wire, bundle, journal = source_fixture(rig, settings, monkeypatch, tmp_path)
        assert verify_source_closure(manifest)
        restore_objects(restore, bundle, manifest, journal)
        assert [event[0] for event in wire.events].index("copy") < [event[0] for event in wire.events].index("upload")
        journal.chmod(0o444)
        with pytest.raises(ObjectRestoreError, match="closure differs"):
            verify_source_closure(manifest)  # New refs require exact journal proof.
        refs, copies = recovery_references(restore, journal, manifest_objects(manifest))
        assert len(refs) == len(copies) == 1
        assert str(restore.pk) in refs[0].object_key
        assert verify_restored_objects(restore, manifest, journal) == 1
        assert all(stream.closed for stream in wire.streams)
        assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED


@pytest.mark.parametrize("fault", ["bytes", "size", "metadata", "content-type", "header"])
def test_archived_rollback_bytes_are_never_exempt_from_streamed_source_readback(tmp_path, settings, monkeypatch, fault):
    with marker_rig(tmp_path) as rig:
        restore, manifest, wire, bundle, journal = source_fixture(rig, settings, monkeypatch, tmp_path)
        restore_objects(restore, bundle, manifest, journal)
        journal.chmod(0o444)
        source_key = manifest["storage"]["objects"][0]["key"]
        obj = wire.objects[source_key]
        if fault == "bytes": obj["payload"] = b"X" * len(obj["payload"])
        elif fault == "size": obj["payload"] += b"extra"
        elif fault == "metadata": obj["Metadata"] = {"forged": "true"}
        elif fault == "content-type": obj["ContentType"] = "text/plain"
        else: obj["CacheControl"] = "public"
        with pytest.raises(ObjectRestoreError):
            verify_restored_objects(restore, manifest, journal)
        assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED
        assert all(stream.closed for stream in wire.streams)


@pytest.mark.parametrize("fault", ["other-op", "wrong-row", "owner", "missing-outcome", "extra-ref"])
def test_prefix_and_model_never_replace_exact_current_operation_journal_proof(tmp_path, settings, monkeypatch, fault):
    with marker_rig(tmp_path) as rig:
        restore, manifest, wire, bundle, journal = source_fixture(rig, settings, monkeypatch, tmp_path)
        restore_objects(restore, bundle, manifest, journal)
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        if fault == "other-op": rows[0]["restore_id"] = "670a9c81-1234-4aaa-8c81-0123456789ab"
        elif fault == "wrong-row": rows[0]["row_id"] += 100000
        elif fault == "owner": rows[0]["module_key"] = "inventory"
        elif fault == "missing-outcome": rows.pop()
        else:
            RestoreRollbackObject.objects.create(restore=restore, bucket_kind="private", source_key="unexplained",
                copy_key=f"rollback/{restore.pk}/private/unexplained", expires_at=timezone.now() + timedelta(days=7))
        journal.write_text("".join(json.dumps(row) + "\n" for row in rows))
        journal.chmod(0o444)
        with pytest.raises(ObjectRestoreError):
            verify_restored_objects(restore, manifest, journal)
        assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED


def test_source_closure_refusal_precedes_new_rollback_rows_or_journal(tmp_path, settings, monkeypatch):
    with marker_rig(tmp_path) as rig:
        restore, manifest, wire, bundle, journal = source_fixture(rig, settings, monkeypatch, tmp_path)
        RestoreRollbackObject.objects.create(restore=restore, bucket_kind="private", source_key="unknown",
            copy_key="rollback/unknown-prefix/private/unexplained", expires_at=timezone.now() + timedelta(days=7))
        before = RestoreRollbackObject.objects.count()
        with pytest.raises(ObjectRestoreError, match="closure differs"):
            restore_objects(restore, bundle, manifest, journal)
        assert RestoreRollbackObject.objects.count() == before
        assert not journal.exists() and wire.events == []


@pytest.mark.parametrize("history", [None, "final", "staging"])
def test_terminal_expired_evidence_requires_all_final_and_staging_versions_absent(tmp_path, settings, monkeypatch, history):
    from apps.accounts.models import User
    from apps.evidence.models import EvidencePhoto, EvidenceObjectRetentionState
    from apps.makerspaces.models import Makerspace
    from apps.backup.object_reference_capture import build_object_ownership_plan

    with marker_rig(tmp_path) as rig:
        actor = User.objects.create_superuser(username="expired-recovery-proof", password="unused")
        maker = Makerspace.objects.create(name="Expired recovery", slug="expired-recovery")
        photo = EvidencePhoto.objects.create(makerspace=maker, uploaded_by=actor, evidence_type="issue", object_key="evidence/expired-proof")
        EvidenceObjectRetentionState.objects.create(evidence=photo, status="expired", object_expired_at=timezone.now(), expired_size_bytes=9)
        closure = build_object_ownership_plan(()).closure("main")["private"][photo.object_key]
        item = {**closure, "bucket_kind": "private", "key": photo.object_key, "version_id": None,
            "size": 0, "sha256": "", "metadata": {}, "headers": {}, "content_type": ""}
        manifest = {"format": FULL_FORMAT, "capture_id": rig.operation.capture_id, "storage": {"objects": [item]}}
        archive = archive_row(archive_sha256=ARTIFACT, manifest=manifest)
        restore = RestoreOperation.objects.create(id=RESTORE_ID, archive=archive, kind="disaster")
        settings.SPACEWORKS_HOST_MARKER_PATH = str(rig.marker)
        write_marker_fsynced(rig.marker, marker_payload(MarkerState.RESTORE_BLOCKED, rig.identity, operation=rig.operation))
        journal = tmp_path / "journal.jsonl"
        journal.write_bytes(b"")
        journal.chmod(0o444)
        wire = ObjectWire()
        monkeypatch.setattr(storage, "client", lambda: wire)
        if history:
            key = ("staging/" if history == "staging" else "") + photo.object_key
            wire.versions[key] = ["retained-version-behind-delete-marker"]
            with pytest.raises(storage.BackupStorageError, match="retained versions"):
                verify_restored_objects(restore, manifest, journal)
        else:
            assert verify_restored_objects(restore, manifest, journal) == 1
            assert ("versions", photo.object_key) in wire.events
            assert ("versions", "staging/" + photo.object_key) in wire.events
        assert not any(event[0] == "get" for event in wire.events)
        assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED
