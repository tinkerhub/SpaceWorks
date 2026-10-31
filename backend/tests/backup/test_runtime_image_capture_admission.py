"""FULL identity admission in real PostgreSQL snapshots, with no provider access."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup import archive_builder, archive_payload, services_archives
from apps.backup.compound_archive import CompoundCapture
from apps.backup.errors import BackupBuildError
from apps.backup.models import BackupArchive, BackupArtifactLedger, BackupLease, PlatformBackupSettings
from apps.backup.runtime_image_identity import RuntimeImageIdentityError
from tests.backup.full_backup_capture_helpers import archive, capture, space
from tests.backup.full_backup_fixture_helpers import OCI, PLATFORM
from tests.backup.full_backup_storage_helpers import install_store
from tests.backup.runtime_image_capture_support import (
    exported_readonly_snapshot, forbid_capture_io, set_digest,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("digest,reason", [
    pytest.param(None, "runtime_image_digest_missing", id="absent"),
    pytest.param("", "runtime_image_digest_missing", id="empty-compose-default"),
    pytest.param("sha256:" + "a" * 63, "runtime_image_digest_invalid", id="short"),
    pytest.param("sha256:" + "A" * 64, "runtime_image_digest_invalid", id="uppercase"),
    pytest.param("registry.example/backend@" + OCI, "runtime_image_digest_invalid", id="repository-ref"),
    pytest.param("c" * 64, "runtime_image_digest_invalid", id="bare-config-id"),
    pytest.param(OCI + "\nprivate-operator-input", "runtime_image_digest_invalid", id="unsafe-suffix"),
])
def test_full_refuses_unprovisioned_digest_before_identity_dump_or_provider(
    tmp_path, monkeypatch, digest, reason,
):
    space()
    set_digest(monkeypatch, digest)
    value = capture(archive(), tmp_path)
    calls = forbid_capture_io(monkeypatch)
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(RuntimeImageIdentityError) as refused:
            archive_payload._snapshot_payload(
                value.archive, tmp_path, value._kwargs["modes"],
                value._kwargs["platform_recipients"], compound_capture=value,
            )
    assert isinstance(refused.value, BackupBuildError)
    assert refused.value.reason == reason
    message = str(refused.value)
    assert message.startswith(reason + ":")
    assert "scripts/provision-runtime-image.py --env-file <static-env> --image <repository:tag>" in message
    assert "refresh trusted Compose records" in message
    assert "private-operator-input" not in message
    assert any("pg_export_snapshot()" in query["sql"] for query in queries)
    assert any("REPEATABLE READ, READ ONLY" in query["sql"] for query in queries)
    assert value.is_full and value._compound is None
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_empty_population_also_requires_full_runtime_identity(tmp_path, monkeypatch):
    set_digest(monkeypatch, None)
    value = capture(archive(), tmp_path)
    calls = forbid_capture_io(monkeypatch)
    with exported_readonly_snapshot():
        with pytest.raises(RuntimeImageIdentityError) as refused:
            value.select_from_snapshot()
    assert refused.value.reason == "runtime_image_digest_missing"
    assert value.is_full and value._compound is None
    assert calls == []


def test_missing_digest_keeps_ordinary_makerspace_payload_available(tmp_path, monkeypatch):
    ordinary = space()
    set_digest(monkeypatch, None)
    row = BackupArchive.objects.create(
        scope="makerspace", makerspace=ordinary, superadmin_access_at_decision=True,
        object_key="backup-archives/makerspace/runtime-image-compat.tar.age",
    )
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("full-only work")
        raise AssertionError("Makerspace payload entered FULL capture")

    monkeypatch.setattr(archive_payload, "_pg_dump", forbidden)
    monkeypatch.setattr(archive_payload.storage, "client", forbidden)
    detailed = archive_payload._snapshot_payload(
        row, tmp_path, {"private": "versioned", "public_image": "versioned"},
        [{"public_recipient": PLATFORM}],
    )
    assert detailed["scope"] == "makerspace"
    assert detailed["oci_digest"] == ""
    assert detailed["covered_makerspace_ids"] == [ordinary.pk]
    assert detailed["storage"]["objects"] == []
    assert (tmp_path / "tenant/makerspaces_makerspace.json").is_file()
    assert calls == []


def test_missing_digest_preserves_opaque_compound_selection(tmp_path, monkeypatch):
    space()
    opaque = space(archived_at=timezone.now(), superadmin_access_enabled=False)
    set_digest(monkeypatch, None)
    value = capture(archive(), tmp_path)
    calls = forbid_capture_io(monkeypatch)
    with exported_readonly_snapshot():
        value.select_from_snapshot()
    assert not value.is_full
    assert isinstance(value._compound, CompoundCapture)
    assert type(opaque).objects.get(pk=opaque.pk).superadmin_access_enabled is False
    assert calls == []


def test_run_archive_persists_safe_operator_failure_without_publishing(monkeypatch, settings):
    space()
    set_digest(monkeypatch, None)
    settings.BACKUP_AGE_RECIPIENT = PLATFORM
    prior = timezone.now()
    PlatformBackupSettings.objects.update_or_create(pk=1, defaults={"last_success_at": prior})
    # Synthetic versioning/cleanup transport only; all capability, source-gate,
    # population, lease, archive failure and audit decisions run in production.
    modes = {"private": "versioned", "public_image": "versioned"}
    monkeypatch.setattr(archive_builder, "_storage_modes", lambda: modes)
    store = install_store(monkeypatch)
    calls = forbid_capture_io(monkeypatch)
    row = services_archives.create_archive(None, scope="deployment")
    result = services_archives.run_archive(row.pk)
    row.refresh_from_db()
    assert result.status == row.status == "failed"
    assert row.failure_detail.startswith("runtime_image_digest_missing:")
    assert "scripts/provision-runtime-image.py" in row.failure_detail
    assert "refresh trusted Compose records" in row.failure_detail
    assert row.completed_at is not None and row.manifest == {}
    assert not BackupArtifactLedger.objects.filter(pk=row.pk).exists()
    state = PlatformBackupSettings.load()
    assert state.last_success_at == prior and state.last_error == row.failure_detail
    failure = AuditLog.objects.get(action="backup.archive_failed", target_id=str(row.pk))
    assert failure.meta["failure_detail"] == row.failure_detail
    assert not AuditLog.objects.filter(action="backup.archive_completed", target_id=str(row.pk)).exists()
    assert BackupLease.objects.get(name="deployment-backup").holder is None
    assert calls == []
    assert all(operation == "delete" for operation, _key in store.events)
