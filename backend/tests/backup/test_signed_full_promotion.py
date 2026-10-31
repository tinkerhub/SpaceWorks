"""Shared durable publication compares full population and independent capture."""

from copy import deepcopy
import uuid

import pytest
from django.db import InternalError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup import artifact_ledger, promotion
from apps.backup.models import B1ActivationState, BackupArchive, BackupRun, PlatformBackupSettings
from tests.backup.full_backup_capture_helpers import archive, freeze_full, prepared, space
from tests.backup.full_backup_fixture_helpers import OCI, make_full_fixture, sha, sign_manifest


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def synthetic_runtime_image_identity(monkeypatch):
    """Satisfy FULL admission only in this module; this is no image attestation."""
    monkeypatch.setenv("SPACEWORKS_OCI_DIGEST", OCI)


@pytest.mark.parametrize("change", [
    "insert", "access", "activation", "archived", "lifecycle", "purging",
    "run-holder", "run-failed",
])
def test_full_publication_refuses_cohort_consent_lifecycle_and_run_drift(tmp_path, change):
    prior = timezone.now()
    settings = PlatformBackupSettings.load()
    settings.last_success_at = prior
    settings.save(update_fields=("last_success_at",))
    ordinary, row, ledger, _build, run = prepared(tmp_path, scheduled=True)
    if change == "insert":
        space()
    elif change == "access":
        type(ordinary).objects.filter(pk=ordinary.pk).update(superadmin_access_enabled=False)
    elif change == "activation":
        B1ActivationState.objects.filter(makerspace=ordinary).update(state="off_pending")
    elif change in {"archived", "lifecycle", "purging"}:
        fields = {"archived": {"archived_at": timezone.now()},
                  "lifecycle": {"lifecycle_state": "importing"},
                  "purging": {"archived_at": timezone.now(), "purge_started_at": timezone.now()}}[change]
        type(ordinary).objects.filter(pk=ordinary.pk).update(**fields)
    elif change == "run-holder":
        BackupRun.objects.filter(pk=run.pk).update(holder=uuid.uuid4())
    elif change == "run-failed":
        BackupRun.objects.filter(pk=run.pk).update(status="failed")
    with pytest.raises(artifact_ledger.ArtifactLedgerMismatch):
        promotion.promote_verified_artifact(ledger.pk)
    row.refresh_from_db()
    ledger.refresh_from_db()
    assert row.status == "running"
    assert ledger.state == "final_verified"
    assert PlatformBackupSettings.load().last_success_at == prior
    assert not AuditLog.objects.filter(action="backup.archive_completed").exists()
    assert ledger.components.get().recipient_associations.filter(tombstoned_at__isnull=True).exists()


@pytest.mark.parametrize("change", ["delete", "run-flags", "run-bool-int", "archive-run-binding"])
def test_forbidden_drift_preserves_database_freeze_and_consistent_publication(tmp_path, change):
    ordinary, row, ledger, _build, run = prepared(tmp_path, scheduled=True)
    before_space = type(ordinary).objects.values().get(pk=ordinary.pk)
    before_run = BackupRun.objects.values().get(pk=run.pk)
    before_archive = BackupArchive.objects.values().get(pk=row.pk)
    before_ledger = type(ledger).objects.values().get(pk=ledger.pk)
    prior_success = PlatformBackupSettings.load().last_success_at
    refusal = ProtectedError if change == "delete" else InternalError
    message = {"delete": "PiiMakerspaceWriteFence",
               "run-flags": "immutable backup run flag_snapshot",
               "run-bool-int": "immutable backup run flag_snapshot",
               "archive-run-binding": "immutable backup archive backup_run"}[change]
    # An independent savepoint absorbs refusal without poisoning later checks.
    with transaction.atomic():
        with pytest.raises(refusal, match=message), transaction.atomic():
            if change == "delete":
                ordinary.delete()
            elif change == "archive-run-binding":
                BackupArchive.objects.filter(pk=row.pk).update(backup_run=None)
            else:
                BackupRun.objects.filter(pk=run.pk).update(
                    flag_snapshot={str(ordinary.pk): 1} if change == "run-bool-int" else {},
                )
    assert type(ordinary).objects.values().get(pk=ordinary.pk) == before_space
    assert BackupRun.objects.values().get(pk=run.pk) == before_run
    assert BackupArchive.objects.values().get(pk=row.pk) == before_archive
    assert type(ledger).objects.values().get(pk=ledger.pk) == before_ledger
    assert PlatformBackupSettings.load().last_success_at == prior_success
    assert not AuditLog.objects.filter(action="backup.archive_completed", target_id=str(row.pk)).exists()
    # No drift took place: a real promotion must still agree with the intact freeze.
    result = promotion.promote_verified_artifact(ledger.pk)
    ledger.refresh_from_db()
    assert result.status == ledger.state == "available"
    assert ledger.frozen_promotion_snapshot == before_ledger["frozen_promotion_snapshot"]
    assert result.backup_run_id == run.pk
    assert BackupRun.objects.values().get(pk=run.pk) == before_run
    # A scheduled archive does not advance the run's global success timestamp.
    assert PlatformBackupSettings.load().last_success_at == prior_success
    assert AuditLog.objects.filter(action="backup.archive_completed", target_id=str(row.pk)).count() == 1


def test_signed_manifest_cannot_replace_independent_source_freeze(tmp_path):
    _ordinary, row, _ledger, build, _run = prepared(tmp_path, final_verified=False)
    # Existing ledger facts are immutable; a second persistence with a freshly
    # signed but different source must refuse rather than overwrite that freeze.
    build.manifest = deepcopy(build.manifest)
    build.manifest["source_capture"]["object_ownership_digest"] = "f" * 64
    from apps.backup.full_manifest import full_source_digest

    build.manifest["main_component"]["semantic_digest"] = full_source_digest(build.manifest["source_capture"])
    build.manifest = sign_manifest(build.manifest)
    with pytest.raises(artifact_ledger.ArtifactLedgerMismatch):
        artifact_ledger.persist_pending(row, build, build.encrypted.stat().st_size)


def test_first_publication_independently_compares_signed_source_to_capture(tmp_path):
    from types import SimpleNamespace
    from apps.backup.full_manifest import full_source_digest

    space()
    row = archive()
    frozen = freeze_full(row, tmp_path / "capture").promotion_snapshot()
    fixture = make_full_fixture(tmp_path, archive_id=row.pk, frozen=frozen, include_objects=False)
    fixture.manifest["source_capture"]["object_ownership_digest"] = "f" * 64
    fixture.manifest["main_component"]["semantic_digest"] = full_source_digest(fixture.manifest["source_capture"])
    fixture.manifest = sign_manifest(fixture.manifest)
    build = SimpleNamespace(manifest=fixture.manifest, promotion_snapshot=frozen,
                            archive_sha256=sha(fixture.encrypted.read_bytes()))
    size = fixture.encrypted.stat().st_size
    ledger = artifact_ledger.persist_pending(row, build, size)
    artifact_ledger.mark_final_verified(ledger.pk, size, build.archive_sha256)
    with pytest.raises(artifact_ledger.ArtifactLedgerMismatch, match="source differs from frozen"):
        promotion.promote_verified_artifact(ledger.pk)
    row.refresh_from_db()
    assert row.status == "running"


def test_full_promotes_with_one_component_and_no_fabricated_partition_proof(tmp_path):
    _ordinary, row, ledger, _build, _run = prepared(tmp_path)
    result = promotion.promote_verified_artifact(ledger.pk)
    assert result.status == "available"
    ledger.refresh_from_db()
    assert ledger.state == "available"
    assert ledger.components.count() == 1
    assert not ({"source_partition_proof", "reservation_manifest", "object_ledgers"} & ledger.outer_manifest.keys())
    assert PlatformBackupSettings.load().last_success_at == result.completed_at
    assert AuditLog.objects.filter(action="backup.archive_completed", target_id=str(row.pk)).count() == 1


def test_available_repromotion_is_idempotent_after_scheduled_run_complete(tmp_path):
    _ordinary, row, ledger, _build, run = prepared(tmp_path, scheduled=True)
    promotion.promote_verified_artifact(ledger.pk)
    row.refresh_from_db()
    completed_at = row.completed_at
    BackupRun.objects.filter(pk=run.pk).update(status="complete", finished_at=timezone.now())
    assert promotion.promote_verified_artifact(ledger.pk).completed_at == completed_at
    assert AuditLog.objects.filter(action="backup.archive_completed").count() == 1
