from datetime import timedelta
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest
from django.utils import timezone

from apps.backup.models import BackupArchive, RestoreOperation
from tests.backup.import_preflight_test_support import make_import_fixture


pytestmark = pytest.mark.django_db


def _restore(actor, fixture):
    archive = BackupArchive.objects.create(
        id=uuid.UUID(fixture.manifest["artifact_id"]),
        scope=BackupArchive.Scope.DEPLOYMENT,
        status=BackupArchive.Status.AVAILABLE,
        age_encrypted=True,
        archive_sha256=fixture.expected_sha256,
        manifest=fixture.manifest,
        object_key="test/compound.tar.age",
        requested_by=actor,
        expires_at=timezone.now() + timedelta(days=1),
    )
    return RestoreOperation.objects.create(
        archive=archive,
        kind=RestoreOperation.Kind.DISASTER,
        requested_by=actor,
    )


@pytest.mark.parametrize("complete_inputs", [False, True])
def test_installed_compound_restore_is_typed_unsupported_before_effects(
    monkeypatch, tmp_path, django_user_model, complete_inputs,
):
    from unittest.mock import Mock
    from apps.backup import backup_control_preflight
    from apps.backup.models import DeploymentRecoveryState

    fixture = make_import_fixture(tmp_path)
    actor = django_user_model.objects.create_superuser(
        username="compound-specific-refusal", password="not-used"
    )
    restore = _restore(actor, fixture)
    stage, manifest = restore.stage, restore.archive.manifest
    recovery = list(DeploymentRecoveryState.objects.values())
    storage = Mock()
    set_stage = Mock()
    monkeypatch.setattr(backup_control_preflight, "storage", storage)
    monkeypatch.setattr(backup_control_preflight, "set_stage", set_stage)
    options = {}
    if complete_inputs:
        options = dict(encrypted_file=str(fixture.encrypted),
                       decrypted_bundle=str(fixture.bundle),
                       continuity_secrets=str(fixture.secrets_file))

    with pytest.raises(CommandError) as refused:
        call_command(
            "backup_control", "preflight", str(restore.pk),
            manifest=str(fixture.manifest_file), bundle=str(tmp_path), **options,
        )

    assert str(refused.value) == (
        "Restore refused [compound_host_unsupported]: this host has no installed "
        "sovereign compound restore coordinator."
    )
    restore.refresh_from_db()
    restore.archive.refresh_from_db()
    assert restore.stage == stage
    assert restore.archive.manifest == manifest
    assert list(DeploymentRecoveryState.objects.values()) == recovery
    assert RestoreOperation.objects.count() == BackupArchive.objects.count() == 1
    storage.assert_not_called()
    assert storage.mock_calls == []
    set_stage.assert_not_called()
