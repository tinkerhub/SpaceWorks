import hashlib

import pytest
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.backup import storage
from apps.backup.archive_import import import_disaster_archive
from apps.backup.digests import ArchiveDigestError, verify_content_ledger
from apps.backup.models import BackupArchive, RestoreOperation
from tests.backup.full_backup_fixture_helpers import make_full_fixture
from tests.backup.full_backup_preflight_helpers import configure_target


@pytest.mark.django_db
def test_import_rejects_missing_expected_digest_before_storage(monkeypatch, tmp_path):
    actor = User.objects.create_superuser(
        username="digest-import-missing", password="secret"
    )
    fixture = make_full_fixture(tmp_path)
    probes = configure_target(monkeypatch, fixture)
    uploads = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: uploads.append(args))

    with pytest.raises(ValidationError, match="expected sha256 digest is required"):
        import_disaster_archive(
            actor, fixture.encrypted, fixture.manifest, bundle=fixture.bundle,
            manifest_file=fixture.manifest_file,
            continuity_secrets_file=fixture.secrets_file,
        )

    assert len(probes) == 2  # Read-only capability probes; no object writes.
    assert uploads == []
    assert BackupArchive.objects.count() == 0
    assert RestoreOperation.objects.count() == 0


def _ledger_entry(path):
    return {
        "path": path.name,
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_required_content_ledger_rejects_empty_ledger(tmp_path):
    with pytest.raises(ArchiveDigestError, match="ledger is required"):
        verify_content_ledger(tmp_path, [], require_ledger=True)


def test_content_ledger_rejects_unlisted_payload_file(tmp_path):
    declared = tmp_path / "database.dump"
    declared.write_bytes(b"database")
    unlisted = tmp_path / "objects.json"
    unlisted.write_bytes(b"objects")

    with pytest.raises(ArchiveDigestError, match="objects.json"):
        verify_content_ledger(tmp_path, [_ledger_entry(declared)])


def test_content_ledger_coverage_ignores_top_level_manifest(tmp_path):
    payload = tmp_path / "database.dump"
    payload.write_bytes(b"database")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

    verify_content_ledger(tmp_path, [_ledger_entry(payload)], require_ledger=True)


def test_content_ledger_rejects_duplicate_paths(tmp_path):
    payload = tmp_path / "database.dump"
    payload.write_bytes(b"database")
    entry = _ledger_entry(payload)

    with pytest.raises(ArchiveDigestError, match="duplicate path database.dump"):
        verify_content_ledger(tmp_path, [entry, entry.copy()], require_ledger=True)
