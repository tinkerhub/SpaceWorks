"""Registered identity plus real full validators gate the supervised state change."""

from datetime import timedelta
import json

import pytest
from django.core.management.base import CommandError
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup.backup_control_preflight import run_restore_preflight
from apps.backup.management.commands.backup_preflight import check_setting_policies
from apps.backup.models import BackupArchive, DeploymentRecoveryState, RestoreOperation
from tests.backup.full_backup_fixture_helpers import BUILD, OCI, make_full_fixture, sha
from tests.backup.full_backup_preflight_helpers import configure_target


pytestmark = pytest.mark.django_db(transaction=True)


def registered(tmp_path, monkeypatch, settings):
    fixture = make_full_fixture(tmp_path)
    probes = configure_target(monkeypatch, fixture)
    settings.BACKUP_OPS_DIR = str(tmp_path)
    monkeypatch.setattr("apps.backup.backup_control_preflight.shutil.which", lambda _name: "/unit-test/tool")
    row = BackupArchive.objects.create(
        id=fixture.manifest["archive_id"], scope="deployment", status="available", manifest=fixture.manifest,
        object_key="preflight-full", age_encrypted=True, expires_at=timezone.now() + timedelta(days=1),
        archive_sha256=sha(fixture.encrypted.read_bytes()),
    )
    restore = RestoreOperation.objects.create(archive=row, kind="disaster", stage="claimed")
    return fixture, restore, probes


def preflight(fixture, restore):
    return run_restore_preflight(
        restore.pk, fixture.manifest_file, current_oci_digest=OCI, bundle_path=fixture.root,
        encrypted_file=fixture.encrypted, decrypted_bundle=fixture.bundle, continuity_secrets=fixture.secrets_file,
        build_info=lambda: dict(BUILD), check_setting_policies=check_setting_policies,
    )


def test_full_preflight_returns_distinct_path_only_after_complete_validation(tmp_path, monkeypatch, settings):
    fixture, restore, probes = registered(tmp_path, monkeypatch, settings)
    assert preflight(fixture, restore) == "full-preflight-ok"
    restore.refresh_from_db()
    assert restore.stage == "preflight"
    assert len(probes) == 4  # Read-only admission and supervised installed capability checks.


@pytest.mark.parametrize("change", ["legacy-header", "signature", "root-bytes", "tar-bytes", "installed-secret"])
def test_full_preflight_refuses_before_stage_audit_and_recovery_state(tmp_path, monkeypatch, settings, change):
    fixture, restore, _probes = registered(tmp_path, monkeypatch, settings)
    if change == "legacy-header":
        fixture.manifest_file.write_text(json.dumps({"format": "spaceworks-phase5a-v1", "partial": False}))
    elif change == "signature":
        manifest = dict(fixture.manifest)
        manifest.pop("archive_signature")
        fixture.manifest_file.write_text(json.dumps(manifest))
    elif change == "root-bytes":
        (fixture.root / "objects/private/evidence/issue.jpg").write_bytes(b"changed")
    elif change == "tar-bytes":
        fixture.write_tar(replacements={"database.dump": b"different"})
    else:
        monkeypatch.setenv("SECRET_KEY", "changed-after-service-recreation")
    before = DeploymentRecoveryState.objects.values().get()
    with pytest.raises(CommandError):
        preflight(fixture, restore)
    restore.refresh_from_db()
    assert restore.stage == "claimed"
    assert DeploymentRecoveryState.objects.values().get() == before
    assert not AuditLog.objects.filter(action__startswith="backup.").exists()
