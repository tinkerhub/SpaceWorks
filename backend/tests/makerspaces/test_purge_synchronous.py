"""Byte-first purge, durable intent, and graph/receipt/final-audit atomicity."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils.dateparse import parse_datetime

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.evidence.models import EvidencePhoto
from apps.inventory.models import InventoryProduct
from apps.makerspaces import lifecycle_purge, purge_intent, purge_storage
from apps.makerspaces.models import Makerspace, PurgeReceipt
from apps.makerspaces.purge_receipts import retry_cleanup
from tests.makerspaces.purge_test_support import (
    actor, archived_space, arm, purge_clock, purge_store,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_first_arm_commits_one_fixed_intent_then_explicit_retry_removes_graph(
    purge_store, purge_clock, settings,
):
    user, space = actor(), archived_space()
    product = InventoryProduct.objects.create(makerspace=space, name="owned", total_quantity=1)
    key = f"evidence/{space.pk}/photo.jpg"
    stage = f"staging/{key}"
    EvidencePhoto.objects.create(makerspace=space, uploaded_by=user, object_key=key, evidence_type="issue")
    bucket = purge_storage.bucket_name("private")
    for locator in (key, stage):
        purge_store.put(bucket, locator, b"old")
        purge_store.put(bucket, locator, b"new")
        purge_store.put(bucket, locator, marker=True)
    original_time = purge_clock.now
    deadline = arm(space, user, purge_clock)
    intent = AuditLog.objects.get(action="makerspace.purge_started").meta
    assert space.purge_started_at == original_time
    assert parse_datetime(intent["not_before"]) == deadline
    assert intent["storage_origins"] == purge_intent.storage_origins()
    assert AuditLog.objects.get(action="makerspace.purge_started").makerspace_id is None
    assert InventoryProduct.objects.filter(pk=product.pk).exists()
    assert not PurgeReceipt.objects.exists() and not purge_store.deletes
    # Changed TTLs cannot silently extend/restart an already committed drain.
    settings.EVIDENCE_URL_TTL_SECONDS += 3600
    purge_clock.now = deadline - timedelta(microseconds=1)
    with pytest.raises(purge_intent.PurgePending) as pending:
        lifecycle_purge.purge(space, user)
    assert pending.value.not_before == deadline
    assert AuditLog.objects.filter(action="makerspace.purge_started").count() == 1
    purge_clock.now = deadline
    original_delete = lifecycle_purge._delete_object_graph
    original_record = audit.record

    def graph_after_verified_bytes(locked):
        assert connection.in_atomic_block
        assert purge_store.objects == {}
        assert not PurgeReceipt.objects.exists()
        original_delete(locked)

    def final_audit_is_atomic(actor, action, **kwargs):
        if action == "makerspace.purged":
            assert connection.in_atomic_block
            assert PurgeReceipt.objects.exists()
        return original_record(actor, action, **kwargs)

    from unittest.mock import patch
    with patch.object(lifecycle_purge, "_delete_object_graph", graph_after_verified_bytes), patch.object(
        audit, "record", final_audit_is_atomic,
    ):
        result = lifecycle_purge.purge(space, user)
    assert not Makerspace.objects.filter(pk=space.pk).exists()
    assert not InventoryProduct.objects.filter(pk=product.pk).exists()
    result.refresh_from_db()
    assert result.last_verified_at == deadline
    assert {("private", key), ("private", stage)} <= set(map(tuple, result.exact_keys))
    final = AuditLog.objects.get(action="makerspace.purged")
    assert final.makerspace_id is None and final.meta["receipt_id"] == str(result.pk)
    # No completion stub: a late presign upload really materializes after graphgone.
    frozen = (result.exact_keys, result.namespace_prefixes)
    late = f"evidence/{space.pk}/rowless-late.jpg"
    purge_store.put(bucket, late, b"late")
    assert purge_store.has_key(bucket, late)
    retry_cleanup(result.pk, user)
    assert not purge_store.objects
    result.refresh_from_db()
    assert (result.exact_keys, result.namespace_prefixes) == frozen
    retry_cleanup(result.pk, user)  # Empty scan never erases future discovery authority.
    purge_store.put(bucket, late, b"later still")
    retry_cleanup(result.pk, user)
    assert not purge_store.objects


def test_intent_audit_failure_rolls_back_timestamp(purge_store, monkeypatch):
    user, space = actor(), archived_space()

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(purge_intent.audit, "record", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        lifecycle_purge.purge(space, user)
    space.refresh_from_db()
    assert space.purge_started_at is None
    assert not AuditLog.objects.filter(action="makerspace.purge_started").exists()
    assert not purge_store.deletes and not PurgeReceipt.objects.exists()


@pytest.mark.parametrize("failure", ["partial", "storage", "listing", "readback", "acknowledgement", "graph", "audit"])
def test_unconfirmed_attempt_retains_graph_intent_and_no_receipt(
    failure, purge_store, purge_clock, monkeypatch,
):
    user, space = actor(), archived_space()
    product = InventoryProduct.objects.create(makerspace=space, name="retained", total_quantity=1)
    key = f"evidence/{space.pk}/rowless"
    purge_store.put(purge_storage.bucket_name("private"), key)
    arm(space, user, purge_clock)
    started = space.purge_started_at
    record = audit.record
    if failure == "graph":
        original = lifecycle_purge._delete_object_graph

        def fail_graph(locked):
            original(locked)
            raise RuntimeError("graph failure")

        monkeypatch.setattr(lifecycle_purge, "_delete_object_graph", fail_graph)
    elif failure == "audit":
        def fail_final(actor, action, **kwargs):
            if action == "makerspace.purged":
                raise RuntimeError("final audit failure")
            return record(actor, action, **kwargs)

        monkeypatch.setattr(audit, "record", fail_final)
    else:
        purge_store.failure = failure
    with pytest.raises((ValidationError, RuntimeError)):
        lifecycle_purge.purge(space, user)
    space.refresh_from_db()
    assert space.purge_started_at == started
    assert InventoryProduct.objects.filter(pk=product.pk).exists()
    assert AuditLog.objects.filter(action="makerspace.purge_started").count() == 1
    assert not AuditLog.objects.filter(action="makerspace.purged").exists()
    assert not PurgeReceipt.objects.exists()


@pytest.mark.parametrize("proof", ["missing", "ambiguous", "origin", "deadline"])
def test_invalid_intent_proof_refuses_before_bytes(proof, purge_store, purge_clock, settings):
    user, space = actor(), archived_space()
    if proof in {"missing", "deadline"}:
        Makerspace.objects.filter(pk=space.pk).update(purge_started_at=purge_clock.now)
        space.refresh_from_db()
        if proof == "deadline":
            audit.record(user, "makerspace.purge_started", meta={
                "makerspace_id": space.pk, "purge_started_at": space.purge_started_at.isoformat(),
                "not_before": (space.purge_started_at - timedelta(seconds=1)).isoformat(),
                "storage_origins": purge_intent.storage_origins(), "purge_intent_version": 1,
            })
    else:
        arm(space, user, purge_clock)
        if proof == "ambiguous":
            audit.record(user, "makerspace.purge_started", meta=purge_intent.load_intent(space))
        else:
            settings.AWS_S3_PUBLIC_ENDPOINT_URL = "https://changed-origin.example.test"
    with pytest.raises(ValidationError):
        lifecycle_purge.purge(space, user)
    assert Makerspace.objects.filter(pk=space.pk).exists()
    assert not purge_store.deletes and not PurgeReceipt.objects.exists()


def test_unsupported_version_listing_refuses_without_arming(purge_store):
    user, space = actor(), archived_space()
    purge_store.failure = "unsupported"
    with pytest.raises(purge_storage.PurgeStorageRefused):
        lifecycle_purge.purge(space, user)
    space.refresh_from_db()
    assert space.purge_started_at is None
    assert not purge_store.deletes and not PurgeReceipt.objects.exists()


def test_slug_changed_since_confirmation_refuses_before_bytes(purge_store, purge_clock):
    user, space = actor(), archived_space()
    arm(space, user, purge_clock)
    Makerspace.objects.filter(pk=space.pk).update(slug="new-exact-confirmation-required")
    with pytest.raises(ValidationError, match="slug changed"):
        lifecycle_purge.purge(space, user)
    assert not purge_store.deletes and not PurgeReceipt.objects.exists()


def test_terminal_import_archives_and_prefixes_survive_as_inert_receipt_authority(
    purge_store, purge_clock, settings,
):
    from pathlib import Path
    from apps.tenant_migration.models import TenantImportJob

    user, space = actor(), archived_space()
    root = Path(settings.BACKUP_OPS_DIR, "tenant-imports")
    root.mkdir(parents=True)
    archive = root / "terminal.tar.age"
    archive.write_bytes(b"encrypted local archive")
    job = TenantImportJob.objects.create(
        actor=user, target_makerspace=space, source_archive_digest="a" * 64,
        status=TenantImportJob.Status.COMPLETED, archive_path=str(archive),
        expires_at=purge_clock.now + timedelta(days=1),
    )
    job_id = job.pk
    key = f"tenant-imports/{job_id}/unreferenced-staging"
    purge_store.put(purge_storage.bucket_name("private"), key)
    arm(space, user, purge_clock)
    result = lifecycle_purge.purge(space, user)
    assert not TenantImportJob.objects.filter(pk=job_id).exists()
    assert not archive.exists()
    assert not purge_store.objects
    assert ["private", f"tenant-imports/{job_id}/"] in result.namespace_prefixes
    late = f"staging/migrated-objects/{job_id}/post-graph-late"
    purge_store.put(purge_storage.bucket_name("private"), late)
    retry_cleanup(result.pk, user)
    assert not purge_store.objects
