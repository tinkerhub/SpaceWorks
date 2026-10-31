"""Even a correctly signed legacy compound artifact has no import authority."""

import base64
from unittest.mock import Mock

import pytest

from apps.backup import import_preflight, outer_manifest
from apps.backup.import_preflight import ImportPreflightError
from apps.backup.models import BackupArchive, RestoreOperation
from apps.ed25519 import decode_key, verify_bytes
from tests.backup.import_preflight_test_support import make_import_fixture, preflight_kwargs

pytestmark = pytest.mark.django_db


def test_signed_compound_v1_refuses_before_pointer_env_ledger_object_or_database_effects(
    monkeypatch, settings, tmp_path,
):
    fixture = make_import_fixture(tmp_path)
    fixture.manifest["protocol_version"] = "spaceworks-lane-e-b1-v1"
    fixture.manifest.pop("source_capture")
    fixture.write()
    # Demonstrate that refusal is the unsupported binding version, not bad signing.
    manifest = dict(fixture.manifest)
    signature = manifest.pop("archive_signature")
    components = [manifest["main_component"], *manifest["slice_components"]]
    public = decode_key(settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY, label="public key", length=32)
    verify_bytes(outer_manifest._signature_payload(manifest, components),
                 base64.b64decode(signature["value"]), public)
    env = tmp_path / ".env"
    env.write_bytes(b"target environment unchanged\n")
    effects = Mock(side_effect=AssertionError("legacy import reached an effect"))
    for name in (
        "apps.backup.storage.upload_archive", "apps.backup.storage.client",
        "apps.audit.services.record", "subprocess.run",
        "apps.backup.host_pointer.write_pointer_atomic", "apps.backup.host_run_ledger.RunLedger.begin",
    ):
        monkeypatch.setattr(name, effects)
    before = (BackupArchive.objects.count(), RestoreOperation.objects.count())
    with pytest.raises(ImportPreflightError) as refusal:
        import_preflight.validate_import_preflight(**preflight_kwargs(fixture))
    assert refusal.value.reason == "source_binding_version"
    assert "v2 backup" in str(refusal.value) and "capabilities" in str(refusal.value)
    assert env.read_bytes() == b"target environment unchanged\n"
    assert not list(tmp_path.glob(".env.pre-restore-*"))
    assert (BackupArchive.objects.count(), RestoreOperation.objects.count()) == before
    effects.assert_not_called()
