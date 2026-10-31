"""Exercise shared ledger, real stream verification and create-only final retries."""

import pytest
from django.utils import timezone

from apps.backup import artifact_protocol, reconciliation, storage
from apps.backup.models import BackupArtifactLedger, BackupRun, PlatformBackupSettings
from tests.backup.full_backup_capture_helpers import prepared
from tests.backup.full_backup_fixture_helpers import OCI
from tests.backup.full_backup_storage_helpers import install_store


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def synthetic_runtime_image_identity(monkeypatch):
    """Satisfy FULL admission only in this module; this is no image attestation."""
    monkeypatch.setenv("SPACEWORKS_OCI_DIGEST", OCI)


def test_full_upload_reads_both_objects_before_publication_and_retains_custody(tmp_path, monkeypatch):
    _ordinary, row, ledger, build, _run = prepared(tmp_path, final_verified=False)
    store = install_store(monkeypatch)
    real_promote = artifact_protocol.promote_verified_artifact

    def promote(identifier):
        assert ("get-final", ledger.final_locator) in store.events
        return real_promote(identifier)

    monkeypatch.setattr(artifact_protocol, "promote_verified_artifact", promote)
    result = artifact_protocol.upload_verify_and_promote(row, build, build.encrypted.stat().st_size)
    assert result.status == "available"
    assert ledger.final_locator in store.objects
    assert ledger.staging_locator not in store.objects
    ledger.refresh_from_db()
    assert ledger.cleanup_pending is False
    assert ledger.components.get().recipient_associations.filter(tombstoned_at__isnull=True).exists()


@pytest.mark.parametrize("boundary", ["upload", "get-staging", "create-final", "get-final"])
def test_transport_failure_does_not_publish_or_replace_previous_success(tmp_path, monkeypatch, boundary):
    prior = timezone.now()
    PlatformBackupSettings.objects.update_or_create(pk=1, defaults={"last_success_at": prior})
    _ordinary, row, ledger, build, _run = prepared(tmp_path, final_verified=False)
    store = install_store(monkeypatch)
    store.fail_at = boundary
    with pytest.raises((OSError, storage.BackupStorageError)):
        artifact_protocol.upload_verify_and_promote(row, build, build.encrypted.stat().st_size)
    row.refresh_from_db()
    assert row.status == "running"
    assert PlatformBackupSettings.load().last_success_at == prior
    assert ledger.components.get().recipient_associations.filter(tombstoned_at__isnull=True).exists()


def test_conditional_final_race_reconciles_existing_verified_bytes_without_replacing(tmp_path, monkeypatch):
    _ordinary, row, ledger, build, _run = prepared(tmp_path, final_verified=False)
    store = install_store(monkeypatch)
    store.objects[ledger.final_locator] = build.encrypted.read_bytes()
    with pytest.raises(storage.BackupStorageError, match="already exists"):
        artifact_protocol.upload_verify_and_promote(row, build, build.encrypted.stat().st_size)
    before_creates = store.events.count(("create-final", ledger.final_locator))
    reconciliation._reconcile_pending(ledger.pk)
    row.refresh_from_db()
    assert row.status == "available"
    assert store.events.count(("create-final", ledger.final_locator)) == before_creates
    assert store.objects[ledger.final_locator] == build.encrypted.read_bytes()


def test_final_readback_retry_and_later_cleanup_keep_published_recipients(tmp_path, monkeypatch):
    _ordinary, row, ledger, build, _run = prepared(tmp_path, final_verified=False)
    store = install_store(monkeypatch)
    store.fail_at = "get-final"
    with pytest.raises(storage.BackupStorageError):
        artifact_protocol.upload_verify_and_promote(row, build, build.encrypted.stat().st_size)
    store.fail_at, store.cleanup_ok = None, False
    reconciliation._reconcile_pending(ledger.pk)
    ledger.refresh_from_db()
    assert ledger.state == "available" and ledger.cleanup_pending
    store.cleanup_ok = True
    reconciliation.reconcile_artifact_uploads()
    ledger.refresh_from_db()
    assert not ledger.cleanup_pending
    assert ledger.final_locator in store.objects
    assert ledger.components.get().recipient_associations.filter(tombstoned_at__isnull=True).exists()


def test_corrupt_racing_final_cannot_be_published(tmp_path, monkeypatch):
    _ordinary, row, ledger, build, _run = prepared(tmp_path, final_verified=False)
    store = install_store(monkeypatch)
    store.objects[ledger.final_locator] = b"wrong final bytes"
    with pytest.raises(storage.BackupVerificationError):
        reconciliation._reconcile_pending(ledger.pk)
    row.refresh_from_db()
    assert row.status == "running"


def test_failed_run_during_reconciliation_is_tombstoned_and_prior_success_preserved(tmp_path, monkeypatch):
    prior = timezone.now()
    PlatformBackupSettings.objects.update_or_create(pk=1, defaults={"last_success_at": prior})
    _ordinary, row, ledger, build, run = prepared(tmp_path, scheduled=True, final_verified=False)
    store = install_store(monkeypatch)
    store.objects[ledger.final_locator] = build.encrypted.read_bytes()
    BackupRun.objects.filter(pk=run.pk).update(status="failed")
    reconciliation.reconcile_artifact_uploads()
    ledger.refresh_from_db()
    row.refresh_from_db()
    assert ledger.state == BackupArtifactLedger.State.FAILED
    assert row.status == "failed"
    assert PlatformBackupSettings.load().last_success_at == prior
