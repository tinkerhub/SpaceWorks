"""Whole-tenant cleanup inherits exact pending/completed aliases, then revokes modules."""
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.backup.models import RestoreOperation
from apps.makerspaces import lifecycle_purge
from apps.makerspaces.models import Makerspace, ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_storage import bucket_name
from tests.backup.test_restore_services import restore_fixture
from tests.makerspaces.module_cleanup_support import (
    actor, module_space, module_store, purge_archived_tenant, rollback, seed_versions,
)
from tests.makerspaces.purge_test_support import arm, purge_clock


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("completed", [False, True], ids=["pending", "completed"])
def test_whole_tenant_inherits_both_final_and_staging_rollback_aliases_and_invalidates(completed, module_store, purge_clock):
    space, user = module_space(), actor()
    _, restore = restore_fixture(stage=RestoreOperation.Stage.COMPLETED)
    # Typed rollback copies sit outside ordinary tenant and module prefixes.
    source = f"procurement/{space.pk}/987/receipts/{'a' * 32}.pdf"
    rb = rollback(restore, space, "procurement", "private", source)
    doomed = seed_versions(module_store, "private", source)
    doomed |= seed_versions(module_store, "private", rb.copy_key)
    module_store.failure = None if completed else "storage"
    if completed:
        module_row, _ = purge_module(space, "procurement", user)
        doomed = seed_versions(module_store, "private", source)
        doomed |= seed_versions(module_store, "private", rb.copy_key)
    else:
        with pytest.raises(ValidationError):
            purge_module(space, "procurement", user)
        module_row = ModulePurgeReceipt.objects.get()
    module_store.failure = None
    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    space.refresh_from_db()
    arm(space, user, purge_clock)
    full = lifecycle_purge.purge(space, user)
    assert not (doomed & module_store.objects.keys())
    for key in (source, f"staging/{source}", rb.copy_key, f"staging/{rb.copy_key}"):
        assert ["private", key] in full.exact_keys
    module_row.refresh_from_db()
    assert module_row.invalidated_at and module_row.invalidation_reason == "tenant_purged"
    assert not Makerspace.objects.filter(pk=space.pk).exists()
    module_store.calls.clear()
    with pytest.raises(ValidationError):
        retry_cleanup(module_row.pk, user)
    assert module_store.calls == []


@pytest.mark.django_db(transaction=True)
def test_reused_raw_id_cannot_inherit_old_module_authority(module_store, purge_clock):
    space, user = module_space(), actor()
    row, _ = purge_module(space, "events", user)
    maker_id = space.pk
    full = purge_archived_tenant(space, user, purge_clock)
    row.refresh_from_db()
    assert full.graph_purged_at and not Makerspace.objects.filter(pk=maker_id).exists()
    assert row.invalidated_at and row.invalidation_reason == "tenant_purged"
    retained = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    code = "NEW1" if row.source_public_code != "NEW1" else "NEW2"
    replacement = module_space("replacement-incarnation", pk=maker_id, public_code=code)
    key = f"event/{maker_id}/{'a' * 32}.png"
    identity = module_store.put(bucket_name("public_image"), key)
    module_store.calls.clear()
    # Supported tenant purge revokes the receipt before a reused ID is considered.
    with pytest.raises(ValidationError, match="invalidated"):
        retry_cleanup(row.pk, user)
    assert identity in module_store.objects and module_store.calls == []
    assert replacement.public_code != row.source_public_code
    assert replacement.created_at != row.source_created_at
    assert Makerspace.objects.filter(pk=maker_id, public_code=code).exists()
    assert ModulePurgeReceipt.objects.values().get(pk=row.pk) == retained


@pytest.mark.django_db(transaction=True)
def test_incompatible_module_handoff_refuses_before_tenant_byte_phase(module_store, purge_clock, settings):
    from apps.makerspaces.models import PurgeReceipt
    from tests.makerspaces.module_cleanup_support import module_receipt

    space, user = module_space(), actor()
    row = module_receipt(space, completed=True)
    identity = module_store.put(bucket_name("public_image"), f"event/{space.pk}/{'a' * 32}.png")
    settings.AWS_STORAGE_BUCKET_NAME = "new-physical-private-origin"
    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    space.refresh_from_db()
    arm(space, user, purge_clock)
    with pytest.raises(ValidationError, match="Incompatible"):
        lifecycle_purge.purge(space, user)
    assert identity in module_store.objects and not module_store.deletes
    row.refresh_from_db()
    assert row.invalidated_at is None and not PurgeReceipt.objects.exists()
    assert Makerspace.objects.filter(pk=space.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_handoff_invalidation_and_full_receipt_rollback_with_tenant_graph(module_store, purge_clock, monkeypatch):
    from apps.makerspaces.models import PurgeReceipt

    space, user = module_space(), actor()
    row, _ = purge_module(space, "events", user)
    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    space.refresh_from_db()
    arm(space, user, purge_clock)
    original = lifecycle_purge._delete_object_graph

    def fail_graph(locked):
        assert ModulePurgeReceipt.objects.get(pk=row.pk).invalidation_reason == "tenant_purged"
        original(locked)
        raise RuntimeError("after tenant deletion")

    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_purge, "_delete_object_graph", fail_graph)
        with pytest.raises(RuntimeError):
            lifecycle_purge.purge(space, user)
    row.refresh_from_db()
    assert row.invalidated_at is None and Makerspace.objects.filter(pk=space.pk).exists()
    assert not PurgeReceipt.objects.exists()
    full = lifecycle_purge.purge(space, user)
    row.refresh_from_db()
    assert full.graph_purged_at and row.invalidation_reason == "tenant_purged"
