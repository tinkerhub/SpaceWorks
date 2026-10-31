"""Real reference inventory and exact tenant namespaces precede any deletion."""

import pytest
from django.core.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.models import BackupArchive
from apps.evidence.models import EvidencePhoto
from apps.inventory.models import InventoryProduct
from apps.makerspaces import lifecycle_purge, purge_storage
from apps.makerspaces.models import Makerspace, PurgeReceipt
from apps.makerspaces.purge_object_closure import PRIVATE_ROOTS, PUBLIC_ROOTS
from apps.tenant_migration.models import TenantImportJob
from tests.makerspaces.purge_test_support import actor, archived_space, arm, purge_clock, purge_store

pytestmark = pytest.mark.django_db(transaction=True)


def test_rowless_retained_legacy_booking_series_and_staging_prefixes_are_exact(
    purge_store, purge_clock, settings,
):
    user = actor()
    space = archived_space(pk=1, enabled_modules=[])
    survivor = Makerspace.objects.create(pk=11, name="survivor", slug="survivor", storage_bytes_used=77)
    for kind, roots in (("private", PRIVATE_ROOTS), ("public_image", PUBLIC_ROOTS)):
        bucket = purge_storage.bucket_name(kind)
        for root in roots:
            for tenant in (1, 11):
                key = f"{root}/{tenant}/retained-or-rowless"
                purge_store.put(bucket, key)
                purge_store.put(bucket, key, marker=True)
            if kind == "public_image" or root in {"evidence", "machines", "machine", "warranty", "procurement", "event-certificates", "print"}:
                purge_store.put(bucket, f"staging/{root}/1/unconsumed")
                purge_store.put(bucket, f"staging/{root}/11/survivor")
    survivors = {identity: payload for identity, payload in purge_store.objects.items()
                 if "/11/" in identity[1]}
    # Tombstoned modules still contribute namespaces; runtime installation isn't ownership.
    settings.TOMBSTONED_APPS = {"events", "bookings", "machines"}
    arm(space, user, purge_clock)
    result = lifecycle_purge.purge(space, user)
    assert purge_store.objects == survivors
    assert result.namespace_prefixes and result.exact_keys
    survivor.refresh_from_db()
    assert survivor.storage_bytes_used == 77


@pytest.mark.parametrize("reference", ["foreign", "archived", "importing", "global", "unknown", "physical_alias"])
def test_reference_refuses_before_first_delete(reference, purge_store, purge_clock, settings):
    user, space = actor(), archived_space()
    key = f"evidence/{space.pk}/shared"
    bucket = purge_storage.bucket_name("private")
    purge_store.put(bucket, key)
    if reference in {"global", "unknown"}:
        audit.record(user, "machine.document_added" if reference == "global" else "unregistered.object.variant", meta={"object_key": key})
    else:
        foreign = Makerspace.objects.create(name="other", slug="other")
        if reference == "archived":
            Makerspace.objects.filter(pk=foreign.pk).update(archived_at=space.archived_at)
        if reference == "importing":
            Makerspace.objects.filter(pk=foreign.pk).update(lifecycle_state="importing")
        if reference == "physical_alias":
            settings.PUBLIC_IMAGE_BUCKET = settings.AWS_STORAGE_BUCKET_NAME
            InventoryProduct.objects.create(makerspace=foreign, name="alias ref", image_key=key)
        else:
            EvidencePhoto.objects.create(makerspace=foreign, uploaded_by=user, object_key=key, evidence_type="issue")
    before = purge_store.objects.copy()
    arm(space, user, purge_clock)
    with pytest.raises((ValidationError, BackupBuildError)) as exc:
        lifecycle_purge.purge(space, user)
    # Source has distinct typed exceptions for registry and shared-reference refusals.
    assert "reference" in str(exc.value).lower() or "namespace" in str(exc.value).lower()
    assert purge_store.objects == before and not purge_store.deletes
    assert Makerspace.objects.filter(pk=space.pk).exists()
    assert not PurgeReceipt.objects.exists()


def test_unfinished_import_refuses_ownership_without_bytes(purge_store, purge_clock):
    from datetime import timedelta
    from django.utils import timezone

    user, space = actor(), archived_space()
    TenantImportJob.objects.create(source_archive_digest="f" * 64, expires_at=timezone.now() + timedelta(days=1))
    arm(space, user, purge_clock)
    with pytest.raises(ValidationError, match="unfinished tenant import"):
        lifecycle_purge.purge(space, user)
    assert not purge_store.deletes
    assert Makerspace.objects.filter(pk=space.pk).exists()


def test_retained_archive_is_foreign_even_when_its_tenant_fk_matches(purge_store, purge_clock):
    user, space = actor(), archived_space()
    key = f"evidence/{space.pk}/retained-archive.age"
    archive = BackupArchive.objects.create(
        scope="makerspace", makerspace=space, requested_by=user, object_key=key,
        superadmin_access_at_decision=space.superadmin_access_enabled,
    )
    purge_store.put(purge_storage.bucket_name("private"), key)
    arm(space, user, purge_clock)
    with pytest.raises(ValidationError, match="foreign or global"):
        lifecycle_purge.purge(space, user)
    assert BackupArchive.objects.filter(pk=archive.pk).exists()
    assert purge_store.has_key(purge_storage.bucket_name("private"), key)
    assert not purge_store.deletes


@pytest.mark.parametrize("owner", ["own", "foreign"])
def test_expired_evidence_tombstone_does_not_hide_late_versions(owner, purge_store, purge_clock):
    from django.utils import timezone
    from apps.evidence.retention_models import EvidenceObjectRetentionState

    user, space = actor(), archived_space()
    key = f"evidence/{space.pk}/expired-but-reuploaded"
    photo_owner = space if owner == "own" else Makerspace.objects.create(name="foreign tombstone", slug="foreign-tombstone")
    photo = EvidencePhoto.objects.create(makerspace=photo_owner, uploaded_by=user, object_key=key, evidence_type="issue")
    EvidenceObjectRetentionState.objects.create(evidence=photo, status="expired", object_expired_at=timezone.now(), expired_size_bytes=12)
    purge_store.put(purge_storage.bucket_name("private"), key, b"late version")
    arm(space, user, purge_clock)
    if owner == "foreign":
        with pytest.raises(ValidationError, match="foreign or global"):
            lifecycle_purge.purge(space, user)
        assert EvidencePhoto.objects.filter(pk=photo.pk).exists()
        assert purge_store.has_key(purge_storage.bucket_name("private"), key)
        assert not purge_store.deletes
    else:
        result = lifecycle_purge.purge(space, user)
        assert ["private", key] in result.exact_keys
        assert not purge_store.has_key(purge_storage.bucket_name("private"), key)
        assert not EvidencePhoto.objects.filter(pk=photo.pk).exists()
