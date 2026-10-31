import pytest
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup import artifact_ledger, reconciliation
from apps.backup.models import (
    B1ActivationState, BackupArchive, BackupArtifactLedger, PlatformBackupSettings,
)
from apps.backup.operation_lock import OperationLockUnavailable, deployment_operation_lock
from tests.backup.test_promotion_e5 import _prepared

pytestmark = pytest.mark.django_db(transaction=True)


def test_real_producer_lock_defers_reconciliation_then_recovers_abandoned_pending(
    monkeypatch, settings, tmp_path,
):
    settings.BACKUP_OPS_DIR = str(tmp_path / "ops" / "work")
    _space, _recipient, archive, ledger, _size, _digest = _prepared(tmp_path)
    ledger_before = BackupArtifactLedger.objects.filter(pk=ledger.pk).values().get()
    archive_before = BackupArchive.objects.filter(pk=archive.pk).values().get()
    activation_before = list(B1ActivationState.objects.values())
    platform_before = list(PlatformBackupSettings.objects.values())
    remote_calls = []

    def remote(operation, key):
        assert not connection.in_atomic_block
        remote_calls.append((operation, key))
        return operation != "exists"

    monkeypatch.setattr(reconciliation.storage, "object_exists", lambda key: remote("exists", key))
    monkeypatch.setattr(reconciliation.storage, "delete_archive", lambda key: remote("delete", key))
    monkeypatch.setattr(reconciliation.storage, "delete_archive_prefix", lambda key: remote("prefix", key))
    monkeypatch.setattr(reconciliation.storage, "stream_verify", lambda *a, **kw: remote("verify", a[0]))
    def create_final(staging, final, **kwargs):
        assert (staging, final) == (ledger.staging_locator, ledger.final_locator)
        assert kwargs == {"expected_size": _size, "expected_sha256": _digest}
        return remote("copy", staging)

    monkeypatch.setattr(reconciliation.storage, "create_final_from_staging", create_final)

    # This is the producer's real filesystem lock, with a second nonblocking open
    # by reconciliation. No threads or mocked lock primitive are involved.
    with deployment_operation_lock():
        assert reconciliation.reconcile_artifact_uploads() == 0
        assert remote_calls == []
        assert BackupArtifactLedger.objects.filter(pk=ledger.pk).values().get() == ledger_before
        assert BackupArchive.objects.filter(pk=archive.pk).values().get() == archive_before
        assert list(B1ActivationState.objects.values()) == activation_before
        assert list(PlatformBackupSettings.objects.values()) == platform_before
        assert not AuditLog.objects.filter(action="backup.archive_failed", target_id=str(archive.pk)).exists()

    assert reconciliation.reconcile_artifact_uploads() == 1

    ledger.refresh_from_db()
    archive.refresh_from_db()
    assert ledger.state == BackupArtifactLedger.State.FAILED
    assert archive.status == BackupArchive.Status.FAILED
    assert ledger.cleanup_pending is False
    assert ("exists", ledger.staging_locator) in remote_calls
    assert ("exists", ledger.final_locator) in remote_calls
    assert ("delete", ledger.staging_locator) in remote_calls
    assert ("delete", ledger.final_locator) in remote_calls
    assert list(B1ActivationState.objects.values()) == activation_before
    assert AuditLog.objects.filter(action="backup.archive_failed", target_id=str(archive.pk)).count() == 1
    calls_after_recovery = list(remote_calls)
    assert reconciliation.reconcile_artifact_uploads() == 0
    assert remote_calls == calls_after_recovery


def test_real_producer_lock_also_excludes_terminal_artifact_cleanup(
    monkeypatch, settings, tmp_path,
):
    settings.BACKUP_OPS_DIR = str(tmp_path / "ops" / "work")
    _space, _recipient, archive, ledger, size, digest = _prepared(tmp_path)
    artifact_ledger.mark_final_verified(ledger.pk, size, digest)
    BackupArtifactLedger.objects.filter(pk=ledger.pk).update(
        state=BackupArtifactLedger.State.AVAILABLE,
        cleanup_pending=True, promoted_at=timezone.now(),
    )
    before = BackupArtifactLedger.objects.filter(pk=ledger.pk).values().get()
    archive_before = BackupArchive.objects.filter(pk=archive.pk).values().get()
    deleted = []

    def delete(key):
        assert not connection.in_atomic_block
        deleted.append(key)
        return True

    monkeypatch.setattr(reconciliation.storage, "delete_archive", delete)

    with deployment_operation_lock():
        assert reconciliation.reconcile_artifact_uploads() == 0
        assert deleted == []
        assert BackupArtifactLedger.objects.filter(pk=ledger.pk).values().get() == before
        assert BackupArchive.objects.filter(pk=archive.pk).values().get() == archive_before

    assert reconciliation.reconcile_artifact_uploads() == 0

    ledger.refresh_from_db()
    assert ledger.state == BackupArtifactLedger.State.AVAILABLE
    assert ledger.cleanup_pending is False
    assert deleted == [ledger.staging_locator]
    assert BackupArchive.objects.filter(pk=archive.pk).values().get() == archive_before
    assert reconciliation.reconcile_artifact_uploads() == 0
    assert deleted == [ledger.staging_locator]


def test_remote_verification_and_cleanup_hold_operation_lock_without_row_transactions(
    monkeypatch, settings, tmp_path,
):
    settings.BACKUP_OPS_DIR = str(tmp_path / "ops" / "work")
    _space, _recipient, archive, ledger, size, digest = _prepared(tmp_path)
    remote_calls = []

    def observe(operation, key):
        assert not connection.in_atomic_block
        # Reconciliation must retain the producer lock throughout remote I/O.
        with pytest.raises(OperationLockUnavailable):
            with deployment_operation_lock():
                pass
        remote_calls.append((operation, key))

    def exists(key):
        observe("exists", key)
        return key == ledger.final_locator

    def verify(key, **kwargs):
        observe("verify", key)
        assert kwargs == {"expected_size": size, "expected_sha256": digest}
        return size, digest

    def delete(key):
        observe("delete", key)
        return True

    monkeypatch.setattr(reconciliation.storage, "object_exists", exists)
    monkeypatch.setattr(reconciliation.storage, "stream_verify", verify)
    monkeypatch.setattr(reconciliation.storage, "delete_archive", delete)

    assert reconciliation.reconcile_artifact_uploads() == 1

    archive.refresh_from_db()
    ledger.refresh_from_db()
    assert archive.status == BackupArchive.Status.AVAILABLE
    assert ledger.state == BackupArtifactLedger.State.AVAILABLE
    assert ledger.cleanup_pending is False
    assert remote_calls == [
        ("exists", ledger.final_locator), ("exists", ledger.staging_locator),
        ("verify", ledger.final_locator), ("delete", ledger.staging_locator),
    ]
