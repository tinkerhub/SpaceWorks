"""Registration and shipped host boundaries refuse before durable side effects."""

from copy import deepcopy
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup import storage
from apps.backup.archive_import import import_disaster_archive
from apps.backup.errors import BackupBuildError
from apps.backup.manifest_dispatch import registered_manifest_kind
from apps.backup.models import BackupArchive, DeploymentRecoveryState, RestoreOperation
from apps.backup.restore_services import request_restore
from tests.backup.full_backup_fixture_helpers import make_full_fixture
from tests.backup.full_backup_preflight_helpers import command_options, configure_target
from tests.backup.import_preflight_test_support import make_import_fixture


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("change", ["legacy-header", "remove-signature", "remove-protocol", "protocol"])
def test_registered_full_cannot_downgrade_to_extracted_legacy(tmp_path, change):
    registered = make_full_fixture(tmp_path).manifest
    extracted = deepcopy(registered)
    if change == "legacy-header":
        extracted = {"format": "spaceworks-phase5a-v1", "partial": False}
    elif change == "remove-signature":
        extracted.pop("archive_signature")
    elif change == "remove-protocol":
        extracted.pop("protocol_version")
    else:
        extracted["protocol_version"] = "spaceworks-phase5a-v1"
    with pytest.raises(BackupBuildError, match="registered signed identity"):
        registered_manifest_kind(registered, extracted)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_registered_historical_unsigned_legacy_remains_recognized(version):
    manifest = {"format": f"spaceworks-phase5a-v{version}", "partial": False}
    assert registered_manifest_kind(manifest, deepcopy(manifest)) == "legacy"


def test_registered_b1_signature_identity_cannot_be_relabelled_as_unsigned_legacy(tmp_path):
    fixture = make_import_fixture(tmp_path)
    with pytest.raises(BackupBuildError, match="registered signed identity"):
        registered_manifest_kind(fixture.manifest, {"format": "spaceworks-phase5a-v1", "partial": False})


def test_raw_import_without_authenticated_bundle_cannot_upload_or_register(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    actor = User.objects.create_superuser(username="raw-full", password="unused")
    calls = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: calls.append(args))
    before = DeploymentRecoveryState.objects.values().get()
    with pytest.raises(ValidationError, match="Authenticated full bundle"):
        import_disaster_archive(actor, fixture.encrypted, fixture.manifest,
                                expected_sha256=fixture.kwargs()["expected_sha256"])
    assert calls == []
    assert not BackupArchive.objects.exists()
    assert not RestoreOperation.objects.exists()
    assert not AuditLog.objects.filter(action__startswith="backup.").exists()
    assert DeploymentRecoveryState.objects.values().get() == before


def test_authenticated_installed_full_import_records_intent_and_import_audit(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    actor = User.objects.create_superuser(username="valid-full-import", password="unused")
    uploads = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: uploads.append(args))
    restore = import_disaster_archive(actor, fixture.encrypted, fixture.manifest,
                                      expected_sha256=fixture.kwargs()["expected_sha256"], bundle=fixture.bundle,
                                      manifest_file=fixture.manifest_file, continuity_secrets_file=fixture.secrets_file)
    assert restore.stage == "requested" and restore.kind == "disaster"
    assert restore.archive.manifest == fixture.manifest
    assert len(uploads) == 1
    assert set(AuditLog.objects.filter(action__startswith="backup.").values_list("action", flat=True)) == {
        "backup.archive_imported", "backup.restore_requested",
    }


def test_raw_import_repeats_installed_settings_admission_before_upload(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    actor = User.objects.create_superuser(username="installed-full-import", password="unused")
    uploads = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: uploads.append(args))
    monkeypatch.setenv("SECRET_KEY", "installed-different-from-prospective")
    with pytest.raises(ValidationError, match="settings_policy"):
        import_disaster_archive(actor, fixture.encrypted, fixture.manifest,
                                expected_sha256=fixture.kwargs()["expected_sha256"], bundle=fixture.bundle,
                                manifest_file=fixture.manifest_file, continuity_secrets_file=fixture.secrets_file)
    assert uploads == []
    assert not BackupArchive.objects.exists()
    assert not RestoreOperation.objects.exists()


@pytest.mark.parametrize("partial", [False, True])
def test_b1_shipped_commands_raw_import_and_restore_request_refuse_early(tmp_path, monkeypatch, partial):
    fixture = make_import_fixture(tmp_path)
    fixture.manifest["partial"] = partial
    fixture.write()
    actor = User.objects.create_superuser(username="b1-full-looking", password="unused")
    calls = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: calls.append(args))
    before = DeploymentRecoveryState.objects.values().get()
    for command in ("preflight_backup_import", "import_backup_archive"):
        options = command_options(fixture)
        if command == "import_backup_archive":
            options["username"] = actor.username
        with pytest.raises(CommandError, match="compound_host_unsupported"):
            call_command(command, stdout=StringIO(), **options)
    with pytest.raises(ValidationError, match="compound_host_unsupported"):
        import_disaster_archive(actor, fixture.encrypted, fixture.manifest,
                                expected_sha256=fixture.expected_sha256, bundle=fixture.bundle,
                                manifest_file=fixture.manifest_file, continuity_secrets_file=fixture.secrets_file)
    from datetime import timedelta
    from django.utils import timezone

    row = BackupArchive.objects.create(scope="deployment", status="available", manifest=fixture.manifest,
                                       object_key="b1-test", expires_at=timezone.now() + timedelta(days=1))
    with pytest.raises(ValidationError, match="compound_host_unsupported"):
        request_restore(actor, row, "disaster")
    assert calls == []
    assert not RestoreOperation.objects.exists()
    assert not AuditLog.objects.filter(action__startswith="backup.").exists()
    assert DeploymentRecoveryState.objects.values().get() == before


@pytest.mark.parametrize("actor_state", ["missing", "member", "inactive", "suspended"])
def test_import_command_requires_active_eligible_superadmin_before_upload(tmp_path, monkeypatch, actor_state):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    username = "full-import-principal"
    if actor_state != "missing":
        actor = User.objects.create_superuser(username=username, password="unused")
        if actor_state == "member":
            actor.is_superuser = False
            actor.role = User.Role.REQUESTER
        elif actor_state == "inactive":
            actor.is_active = False
        else:
            actor.access_status = "suspended"
        actor.save()
    uploads = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: uploads.append(args))
    with pytest.raises(CommandError):
        call_command("import_backup_archive", username=username, stdout=StringIO(), **command_options(fixture))
    assert uploads == []
    assert not BackupArchive.objects.exists()
    assert not RestoreOperation.objects.exists()
