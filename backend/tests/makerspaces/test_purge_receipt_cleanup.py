"""Receipt is permanent provenance, never an automatic deletion instruction."""

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.recipient_selection import BackupBuildError
from apps.evidence.models import EvidencePhoto
from apps.makerspaces import purge_storage
from apps.makerspaces.models import Makerspace, PurgeReceipt
from apps.makerspaces.purge_receipts import retry_cleanup
from tests.backup.e7_reservation_test_helpers import persist_restore_state
from tests.backup.test_restore_services import restore_fixture
from tests.makerspaces.purge_test_support import actor, purge_store, receipt

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("refusal", ["archived_source", "generation", "invalidated", "origin", "recovery", "opaque_component"])
def test_explicit_retry_requires_current_absent_source_authority(refusal, purge_store, settings):
    user, row = actor(), receipt()
    key = f"evidence/{row.source_makerspace_id}/late"
    purge_store.put(purge_storage.bucket_name("private"), key)
    if refusal == "archived_source":
        Makerspace.objects.create(pk=row.source_makerspace_id, name="restored", slug="restored", archived_at=timezone.now())
    elif refusal == "generation":
        DeploymentRecoveryState.objects.filter(pk=1).update(auth_generation=uuid4())
    elif refusal == "invalidated":
        PurgeReceipt.objects.filter(pk=row.pk).update(invalidated_at=timezone.now())
    elif refusal == "origin":
        settings.AWS_S3_ENDPOINT_URL = "https://other-storage.example.test"
    elif refusal == "recovery":
        DeploymentRecoveryState.objects.filter(pk=1).update(mode=DeploymentRecoveryState.Mode.QUIESCED)
    else:
        persist_restore_state({"component_ids": [str(uuid4())]}, makerspace_id=987654)
    before = purge_store.objects.copy()
    with pytest.raises(ValidationError):
        retry_cleanup(row.pk, user)
    assert purge_store.objects == before and not purge_store.deletes
    row.refresh_from_db()
    assert row.last_verified_at is None
    # Refusals inside authority validation retain a safe failure status only.
    assert row.last_error_code in {"", "cleanup_unconfirmed"}


def test_normal_mode_with_historical_completed_restore_fk_permits_explicit_retry(purge_store):
    user, row = actor(), receipt()
    _, restore = restore_fixture(stage=RestoreOperation.Stage.COMPLETED)
    DeploymentRecoveryState.objects.filter(pk=1).update(active_restore=restore)
    key = f"evidence/{row.source_makerspace_id}/late"
    purge_store.put(purge_storage.bucket_name("private"), key)
    result = retry_cleanup(row.pk, user)
    assert not purge_store.objects
    assert result.last_verified_at is not None
    assert DeploymentRecoveryState.objects.get(pk=1).active_restore_id == restore.pk


@pytest.mark.parametrize("reference", ["remapped_tenant", "global", "unknown"])
def test_current_reference_to_old_namespace_protects_late_bytes(reference, purge_store):
    user, row = actor(), receipt()
    key = f"evidence/{row.source_makerspace_id}/retained-late"
    purge_store.put(purge_storage.bucket_name("private"), key)
    if reference == "remapped_tenant":
        remapped = Makerspace.objects.create(name="remapped", slug="remapped")
        assert remapped.pk != row.source_makerspace_id
        EvidencePhoto.objects.create(makerspace=remapped, uploaded_by=user, object_key=key, evidence_type="issue")
    else:
        audit.record(user, "machine.document_added" if reference == "global" else "unclassified.reference", meta={"object_key": key})
    before = purge_store.objects.copy()
    with pytest.raises((ValidationError, BackupBuildError)):
        retry_cleanup(row.pk, user)
    assert purge_store.objects == before and not purge_store.deletes
    row.refresh_from_db()
    assert row.last_error_code == "cleanup_unconfirmed" and row.last_verified_at is None
    assert AuditLog.objects.get(action="makerspace.purge_receipt_checked").meta["verified"] is False


def test_failed_retry_preserves_last_verified_time_and_permanent_locators(purge_store):
    user, row = actor(), receipt()
    retry_cleanup(row.pk, user)
    row.refresh_from_db()
    verified, prefixes = row.last_verified_at, row.namespace_prefixes
    key = f"event-certificates/{row.source_makerspace_id}/late.pdf"
    purge_store.put(purge_storage.bucket_name("private"), key)
    purge_store.failure = "readback"
    with pytest.raises(purge_storage.PurgeStorageRefused):
        retry_cleanup(row.pk, user)
    row.refresh_from_db()
    assert row.last_verified_at == verified
    assert row.namespace_prefixes == prefixes and row.exact_keys == []
    assert row.last_error_code == "cleanup_unconfirmed"
    assert purge_store.has_key(purge_storage.bucket_name("private"), key)
    purge_store.failure = None
    retry_cleanup(row.pk, user)
    assert not purge_store.objects


def test_creating_and_reading_receipt_never_dispatches_cleanup(purge_store, monkeypatch):
    from config.celery import app
    from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS

    def forbidden_dispatch(*args, **kwargs):
        pytest.fail("inert receipt dispatched automatic work")

    monkeypatch.setattr(app, "send_task", forbidden_dispatch)
    row = receipt()
    key = f"evidence/{row.source_makerspace_id}/late"
    purge_store.put(purge_storage.bucket_name("private"), key)
    assert PurgeReceipt.objects.get(pk=row.pk).namespace_prefixes
    assert not any("purge_receipt" in str(task) for task in SCHEDULED_TASKS)
    assert purge_store.calls == []
    assert purge_store.has_key(purge_storage.bucket_name("private"), key)


def test_retry_rechecks_actor_from_database_before_touching_bytes(purge_store):
    from apps.accounts.models import User

    user, row = actor(), receipt()
    User.objects.filter(pk=user.pk).update(access_status="restricted")
    assert user.access_status == "active"  # Deliberately stale authenticated object.
    with pytest.raises(ValidationError, match="active, unrestricted"):
        retry_cleanup(row.pk, user)
    assert not purge_store.calls


def test_reference_created_during_late_namespace_scan_refuses_before_first_delete(purge_store):
    user, row = actor(), receipt()
    foreign = Makerspace.objects.create(name="restored tenant", slug="restored-tenant")
    key = f"evidence/{row.source_makerspace_id}/newly-referenced"
    purge_store.put(purge_storage.bucket_name("private"), key)

    def reference_during_scan(_params):
        purge_store.on_list = None
        EvidencePhoto.objects.create(makerspace=foreign, uploaded_by=user, object_key=key, evidence_type="issue")

    purge_store.on_list = reference_during_scan
    with pytest.raises(ValidationError, match="reference"):
        retry_cleanup(row.pk, user)
    assert purge_store.has_key(purge_storage.bucket_name("private"), key)
    assert not purge_store.deletes
