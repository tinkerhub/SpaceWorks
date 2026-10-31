"""Actual population/run locks through the production promotion commit."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup import artifact_ledger, promotion
from apps.backup.models import BackupArchive, BackupRun, PlatformBackupSettings
from apps.backup.services_runs import _fail_run
from tests.backup.full_backup_capture_helpers import prepared, space
from tests.backup.full_backup_fixture_helpers import OCI
from tests.backup.full_backup_race_helpers import hold_publication, independent_job, wait_until_blocked


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def synthetic_runtime_image_identity(monkeypatch):
    """Satisfy FULL admission only in this module; this is no image attestation."""
    monkeypatch.setenv("SPACEWORKS_OCI_DIGEST", OCI)


def test_share_population_fence_blocks_insert_until_publication_commit(tmp_path, monkeypatch):
    _ordinary, row, ledger, _build, _run = prepared(tmp_path)
    arrived, release, publisher_pids = hold_publication(monkeypatch)
    inserter_pids = Queue()
    with ThreadPoolExecutor(max_workers=2) as pool:
        publisher = pool.submit(independent_job, lambda: promotion.promote_verified_artifact(ledger.pk))
        try:
            assert arrived.wait(10)
            publisher_pid = publisher_pids.get(timeout=10)
            inserter = pool.submit(independent_job, space, inserter_pids)
            wait_until_blocked(inserter_pids.get(timeout=10), publisher_pid)
            assert not inserter.done()
            assert BackupArchive.objects.get(pk=row.pk).status == "running"
        finally:
            release.set()
        assert publisher.result(timeout=10).status == "available"
        added = inserter.result(timeout=10)
    assert added.pk != _ordinary.pk
    assert AuditLog.objects.filter(action="backup.archive_completed").count() == 1


def test_insertion_committed_on_other_connection_before_fence_refuses(tmp_path):
    prior = timezone.now()
    PlatformBackupSettings.objects.update_or_create(pk=1, defaults={"last_success_at": prior})
    _ordinary, row, ledger, _build, _run = prepared(tmp_path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        added = pool.submit(independent_job, space).result(timeout=10)
    assert type(added).objects.filter(pk=added.pk).exists()
    with pytest.raises(artifact_ledger.ArtifactLedgerMismatch, match="retained"):
        promotion.promote_verified_artifact(ledger.pk)
    assert BackupArchive.objects.get(pk=row.pk).status == "running"
    assert PlatformBackupSettings.load().last_success_at == prior


def test_real_failure_service_waits_for_run_lock_until_publish_commits(tmp_path, monkeypatch):
    _ordinary, row, ledger, _build, run = prepared(tmp_path, scheduled=True)
    arrived, release, publisher_pids = hold_publication(monkeypatch)
    failure_pids = Queue()
    with ThreadPoolExecutor(max_workers=2) as pool:
        publisher = pool.submit(independent_job, lambda: promotion.promote_verified_artifact(ledger.pk))
        try:
            assert arrived.wait(10)
            failure = pool.submit(independent_job, lambda: _fail_run(run, "concurrent failure"), failure_pids)
            wait_until_blocked(failure_pids.get(timeout=10), publisher_pids.get(timeout=10))
            assert not failure.done()
            assert BackupRun.objects.get(pk=run.pk).status == "running"
        finally:
            release.set()
        assert publisher.result(timeout=10).status == "available"
        assert failure.result(timeout=10).status == "failed"
    assert BackupArchive.objects.get(pk=row.pk).status == "available"


def test_failure_lock_acquired_first_blocks_promotion_then_refuses(tmp_path):
    prior = timezone.now()
    PlatformBackupSettings.objects.update_or_create(pk=1, defaults={"last_success_at": prior})
    _ordinary, row, ledger, _build, run = prepared(tmp_path, scheduled=True)
    failed, release, failure_pids, publisher_pids = Event(), Event(), Queue(), Queue()

    def fail_while_locked():
        with transaction.atomic():
            BackupRun.objects.select_for_update().get(pk=run.pk)
            _fail_run(run, "failure committed before publication")
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                failure_pids.put(cursor.fetchone()[0])
            failed.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        failure = pool.submit(independent_job, fail_while_locked)
        try:
            assert failed.wait(10)
            publisher = pool.submit(independent_job, lambda: promotion.promote_verified_artifact(ledger.pk), publisher_pids)
            wait_until_blocked(publisher_pids.get(timeout=10), failure_pids.get(timeout=10))
            assert not publisher.done()
        finally:
            release.set()
        failure.result(timeout=10)
        with pytest.raises(artifact_ledger.ArtifactLedgerMismatch, match="run"):
            publisher.result(timeout=10)
    assert BackupArchive.objects.get(pk=row.pk).status == "running"
    assert PlatformBackupSettings.load().last_success_at == prior
    assert not AuditLog.objects.filter(action="backup.archive_completed").exists()
