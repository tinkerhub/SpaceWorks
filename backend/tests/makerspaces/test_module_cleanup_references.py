"""Deletion authority permits exact doomed holders, never retained shared sites."""
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit import services as audit
from apps.bookings.models import BookableSpace
from apps.events.models import Event
from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_receipt_authority import validate_receipt
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_storage import bucket_name
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from tests.makerspaces.module_cleanup_support import (
    H, actor, event, module_receipt, module_space, module_store, seed_versions,
)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("holder", ["foreign", "othermodule", "core", "global-audit"])
def test_retained_reference_refuses_deletion_and_preserves_both_graphs(holder, module_store, settings):
    space, user = module_space(), actor()
    key = f"event/{space.pk}/{H}.png"
    doomed = event(space, key)
    surviving = None
    if holder == "foreign":
        surviving = event(module_space("foreign-module-holder"), key)
    elif holder == "othermodule":
        surviving = BookableSpace.objects.create(makerspace=space, name="Retained booking", image_key=key)
    elif holder == "core":
        # Physical bucket identity, rather than the logical kind, decides collisions.
        settings.AWS_STORAGE_BUCKET_NAME = settings.PUBLIC_IMAGE_BUCKET
        from apps.evidence.models import EvidencePhoto
        surviving = EvidencePhoto.objects.create(makerspace=space, uploaded_by=user,
                                                 evidence_type="issue", object_key=key)
    else:
        settings.AWS_STORAGE_BUCKET_NAME = settings.PUBLIC_IMAGE_BUCKET
        audit.record(user, "machine.document_added", meta={"object_key": key})
    seeded = seed_versions(module_store, "public_image", key)
    with pytest.raises(ValidationError, match="reference"):
        purge_module(space, "events", user)
    assert seeded <= module_store.objects.keys() and not module_store.deletes
    assert Event.objects.filter(pk=doomed.pk).exists()
    if surviving is not None:
        assert type(surviving).objects.filter(pk=surviving.pk).exists()
    assert not ModulePurgeReceipt.objects.exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("field", ["source_key", "staging_key", "target_key"])
def test_retained_import_locators_never_become_module_owned(field, module_store, settings):
    space, user = module_space(), actor()
    # Use a private module so staging_key's explicitly private bucket is coherent.
    key = f"procurement/{space.pk}/999/receipts/{H}.pdf"
    now = timezone.now()
    job = TenantImportJob.objects.create(
        target_makerspace=space, actor=user, source_archive_digest="a" * 64,
        source_makerspace_id="999", source_makerspace_slug="retained-source",
        source_makerspace_name="Retained source", source_deployment_id="source-test",
        storage_mode="versioned", verification_report={"format_version": 1},
        status=TenantImportJob.Status.COMPLETED, terminal_at=now,
        expires_at=now + timezone.timedelta(days=1),
    )
    values = dict(source_key="source/other", staging_key="tenant-imports/other/staged",
                  target_key="target/other", bucket_kind="private", size=10, sha256="b" * 64)
    values[field] = key
    journal = TenantImportObject.objects.create(job=job, **values)
    seeded = seed_versions(module_store, "private", key)
    with pytest.raises(ValidationError, match="reference"):
        purge_module(space, "procurement", user)
    assert seeded <= module_store.objects.keys() and not module_store.deletes
    journal.refresh_from_db()
    assert getattr(journal, field) == key and not ModulePurgeReceipt.objects.exists()
    job.refresh_from_db()
    assert job.status == TenantImportJob.Status.COMPLETED and job.target_makerspace_id == space.pk


@pytest.mark.django_db(transaction=True)
def test_two_doomed_typed_holders_share_one_public_charge(module_store):
    space, user = module_space(storage_bytes_used=100), actor()
    key = f"event/{space.pk}/{H}.png"
    event(space, key)
    event(space, key)
    module_store.put(bucket_name("public_image"), key, b"1234567")
    receipt, counts = purge_module(space, "events", user)
    assert counts and len(receipt.holder_sites) == 2
    assert len(receipt.charge_obligations) == 1 and receipt.charge_obligations[0][3] == 7
    space.refresh_from_db()
    assert space.storage_bytes_used == 93 and not Event.objects.filter(makerspace=space).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("site", [
    ["bookings.BookableSpace", "1", "image_key", "public_image"],
    ["events.Event", "01", "image_key", "public_image"],
    ["events.Event", "1", "avatar_key", "public_image"],
    ["events.Event", "1", "image_key", "private"],
    ["backup.RestoreRollbackObject", "1", "source_key", "public_image"],
])
def test_exact_holder_allowance_cannot_be_widened_by_module_or_model_guess(site, module_store):
    space = module_space()
    row = module_receipt(space, completed=True)
    key = "legacy/imported/exact.png"
    row.holder_sites = [[*site, key]]
    row.exact_keys = [[site[3], key], [site[3], f"staging/{key}"]]
    with pytest.raises(ValidationError):
        validate_receipt(row)
    assert module_store.calls == []


@pytest.mark.django_db(transaction=True)
def test_completed_receipt_cannot_delete_a_new_current_holder(module_store):
    space, user = module_space(), actor()
    receipt, _ = purge_module(space, "events", user)
    key = f"event/{space.pk}/{H}.png"
    retained = event(space, key)
    seeded = seed_versions(module_store, "public_image", key)
    with pytest.raises(ValidationError, match="reference"):
        retry_cleanup(receipt.pk, user)
    assert seeded <= module_store.objects.keys() and not module_store.deletes
    assert Event.objects.filter(pk=retained.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_exact_typed_legacy_holder_inside_owned_branch_is_authorized_without_grammar_widening(module_store):
    space, user = module_space(storage_bytes_used=100), actor()
    key = f"event/{space.pk}/legacy-accepted.png"
    accepted = event(space, key)
    module_store.put(bucket_name("public_image"), key, b"accepted")
    module_store.put(bucket_name("public_image"), f"staging/{key}", b"old staging")
    receipt, _ = purge_module(space, "events", user)
    assert receipt.graph_purged_at and receipt.charge_obligations[0][3] == 8
    assert not Event.objects.filter(pk=accepted.pk).exists() and not module_store.objects
    assert ["events.Event", str(accepted.pk), "image_key", "public_image", key] in receipt.holder_sites
    space.refresh_from_db()
    assert space.storage_bytes_used == 92


@pytest.mark.django_db
@pytest.mark.parametrize("defect", ["pk", "field", "model", "bucket"])
def test_reference_exclusion_matches_the_whole_typed_site_instead_of_just_key(defect):
    from apps.makerspaces.module_purge_references import assert_unreferenced

    space = module_space()
    key = f"event/{space.pk}/{H}.png"
    row = event(space, key)
    site = ["events.Event", str(row.pk), "image_key", "public_image", key]
    closure = {("public_image", key), ("public_image", f"staging/{key}")}
    assert_unreferenced(closure, [site])
    site[{"pk": 1, "field": 2, "model": 0, "bucket": 3}[defect]] = {
        "pk": str(row.pk + 1), "field": "avatar_key", "model": "events.EventSeries", "bucket": "private",
    }[defect]
    with pytest.raises(ValidationError, match="reference"):
        assert_unreferenced(closure, [site])
