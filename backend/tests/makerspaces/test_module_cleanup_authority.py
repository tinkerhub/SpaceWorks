"""Global receipts are inert retained authority, with SQL-enforced one-way state."""
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, models, transaction
from django.utils import timezone

from apps.backup.models import DeploymentRecoveryState
from apps.makerspaces import lifecycle_purge
from apps.makerspaces.models import Makerspace, ModulePurgeReceipt
from apps.makerspaces.module_install import install_module, apply_profile
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_profiles import FULL
from apps.makerspaces.purge_storage import bucket_name
from tests.makerspaces.module_cleanup_support import (
    H, actor, module_receipt, module_space, module_store,
    privileged_restored_orphan_receipt, purge_archived_tenant,
)
from tests.makerspaces.purge_test_support import purge_clock


@pytest.mark.django_db(transaction=True)
def test_receipt_schema_has_no_fk_secret_or_cascade_and_active_uniqueness(module_store, purge_clock, monkeypatch):
    fields = ModulePurgeReceipt._meta.concrete_fields
    assert not any(isinstance(field, models.ForeignKey) for field in fields)
    assert {field.name for field in fields} == {
        "id", "source_makerspace_id", "source_public_code", "source_created_at", "module_key",
        "auth_generation", "schema_version", "storage_origins", "exact_keys", "namespace_clauses",
        "holder_sites", "charge_obligations", "rollback_bindings", "graph_digest", "intent_created_at",
        "graph_purged_at", "invalidated_at", "invalidation_reason", "last_attempt_at", "last_verified_at",
        "last_error_code",
    }
    space = module_space()
    first = module_receipt(space)
    with pytest.raises(IntegrityError), transaction.atomic():
        module_receipt(space)
    bookings = module_receipt(space, "bookings")
    first.invalidated_at, first.invalidation_reason = timezone.now(), "recovery"
    first.save(update_fields=["invalidated_at", "invalidation_reason"])
    second = module_receipt(space)
    assert second.pk != first.pk
    source_id = space.pk
    original_delete = lifecycle_purge._delete_object_graph

    def check_before_graph(locked):
        assert connection.in_atomic_block
        assert Makerspace.objects.filter(pk=source_id).exists()
        rows = ModulePurgeReceipt.objects.filter(pk__in=[bookings.pk, second.pk])
        assert rows.filter(invalidated_at__isnull=False, invalidation_reason="tenant_purged").count() == 2
        return original_delete(locked)

    monkeypatch.setattr(lifecycle_purge, "_delete_object_graph", check_before_graph)
    full = purge_archived_tenant(space, actor(), purge_clock)
    assert full.graph_purged_at and not Makerspace.objects.filter(pk=source_id).exists()
    assert ModulePurgeReceipt.objects.filter(source_makerspace_id=source_id).count() == 3
    first.refresh_from_db()
    assert first.invalidation_reason == "recovery"
    assert not ModulePurgeReceipt.objects.filter(source_makerspace_id=source_id, invalidated_at__isnull=True).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [
    ("source_makerspace_id", 999), ("source_public_code", "newincarnation"),
    ("module_key", "bookings"), ("graph_digest", "b" * 64), ("exact_keys", []),
    ("namespace_clauses", {}), ("charge_obligations", []), ("holder_sites", []),
    ("auth_generation", uuid4()), ("storage_origins", {}), ("rollback_bindings", []),
])
def test_raw_sql_cannot_rebind_immutable_authority(field, value):
    row = module_receipt(module_space())
    if value == getattr(row, field):
        value = [["untrusted", "widened"]]
    before = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    with pytest.raises(DatabaseError), transaction.atomic():
        ModulePurgeReceipt.objects.filter(pk=row.pk).update(**{field: value})
    assert ModulePurgeReceipt.objects.values().get(pk=row.pk) == before


@pytest.mark.django_db
@pytest.mark.parametrize("mutation", ["graph-reset", "graph-rewrite", "invalidation-reset", "verification-backwards", "delete"])
def test_raw_sql_cannot_reverse_completion_invalidation_or_delete_receipt(mutation):
    row = module_receipt(module_space(), completed=True)
    row.invalidated_at, row.invalidation_reason = timezone.now(), "recovery"
    row.save(update_fields=["invalidated_at", "invalidation_reason"])
    values = {
        "graph-reset": {"graph_purged_at": None},
        "graph-rewrite": {"graph_purged_at": timezone.now() + timezone.timedelta(seconds=1)},
        "invalidation-reset": {"invalidated_at": None, "invalidation_reason": ""},
        "verification-backwards": {"last_verified_at": row.intent_created_at - timezone.timedelta(seconds=1)},
    }
    before = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    with pytest.raises(DatabaseError), transaction.atomic():
        query = ModulePurgeReceipt.objects.filter(pk=row.pk)
        if mutation == "delete":
            query.delete()
        else:
            query.update(**values[mutation])
    assert ModulePurgeReceipt.objects.values().get(pk=row.pk) == before


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["raw-orm", "install", "profile"])
def test_pending_intent_forbids_enable_without_invalidation(entry, module_store):
    space = module_space()
    row = module_receipt(space)
    with pytest.raises((ValidationError, DatabaseError)), transaction.atomic():
        if entry == "raw-orm":
            Makerspace.objects.filter(pk=space.pk).update(enabled_modules=["events"])
        elif entry == "install":
            install_module(space, "events")
        else:
            apply_profile(space, FULL)
    space.refresh_from_db(); row.refresh_from_db()
    assert "events" not in space.enabled_modules and row.invalidated_at is None
    assert module_store.calls == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["raw-orm", "install", "profile"])
def test_completed_enable_invalidates_atomically_before_new_upload_and_stale_retry(entry, module_store):
    space, user = module_space(), actor()
    row, _ = purge_module(space, "events", user)
    with pytest.raises(RuntimeError), transaction.atomic():
        Makerspace.objects.filter(pk=space.pk).update(enabled_modules=["events"])
        assert ModulePurgeReceipt.objects.get(pk=row.pk).invalidated_at is not None
        raise RuntimeError("enable rolled back")
    row.refresh_from_db()
    assert row.invalidated_at is None
    if entry == "raw-orm":
        Makerspace.objects.filter(pk=space.pk).update(enabled_modules=["events"])
    elif entry == "install":
        install_module(space, "events")
    else:
        apply_profile(space, FULL)
    row.refresh_from_db(); space.refresh_from_db()
    assert "events" in space.enabled_modules and row.invalidation_reason == "module_enabled"
    key = f"staging/event/{space.pk}/{H}.png"
    identity = module_store.put(bucket_name("public_image"), key)
    # Even after another uninstall the old authority stays invalidated.
    Makerspace.objects.filter(pk=space.pk).update(enabled_modules=[])
    module_store.calls.clear()
    with pytest.raises(ValidationError, match="invalidated"):
        retry_cleanup(row.pk, user)
    assert identity in module_store.objects and module_store.calls == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("drift", ["generation", "public-code", "created-at", "private-origin", "public-origin", "recovery", "hidden", "actor"])
def test_retry_rechecks_current_authority_before_provider(drift, module_store, settings):
    space, user = module_space(), actor()
    row, _ = purge_module(space, "events", user)
    original = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    if drift == "generation":
        DeploymentRecoveryState.objects.filter(pk=1).update(auth_generation=uuid4())
    elif drift == "public-code":
        replacement_code = "NEW1" if space.public_code != "NEW1" else "NEW2"
        assert replacement_code != row.source_public_code
        Makerspace.objects.filter(pk=space.pk).update(public_code=replacement_code)
    elif drift == "created-at":
        Makerspace.objects.filter(pk=space.pk).update(created_at=space.created_at + timezone.timedelta(seconds=1))
    elif drift == "private-origin":
        settings.AWS_STORAGE_BUCKET_NAME = "replacement-private"
    elif drift == "public-origin":
        settings.AWS_S3_PUBLIC_ENDPOINT_URL = "https://replacement.example.test"
    elif drift == "recovery":
        DeploymentRecoveryState.objects.filter(pk=1).update(mode="quiesced")
    elif drift == "hidden":
        Makerspace.objects.filter(pk=space.pk).update(superadmin_access_enabled=False)
    else:
        type(user).objects.filter(pk=user.pk).update(access_status="restricted")
    module_store.calls.clear()
    with pytest.raises(ValidationError, match="incarnation" if drift == "public-code" else None):
        retry_cleanup(row.pk, user)
    assert module_store.calls == []
    row.refresh_from_db()
    assert row.graph_purged_at and row.last_error_code == ""
    assert ModulePurgeReceipt.objects.values().get(pk=row.pk) == original


@pytest.mark.django_db(transaction=True)
def test_absent_maker_never_grants_orphan_receipt_cleanup_authority(module_store, purge_clock):
    space, user = module_space(), actor()
    row, _ = purge_module(space, "events", user)
    key = f"staging/event/{space.pk}/{H}.png"
    full = purge_archived_tenant(space, user, purge_clock)
    row.refresh_from_db()
    assert full.graph_purged_at and not Makerspace.objects.filter(pk=space.pk).exists()
    assert row.invalidated_at and row.invalidation_reason == "tenant_purged"
    identity = module_store.put(bucket_name("public_image"), key)
    module_store.calls.clear()
    with pytest.raises(ValidationError, match="invalidated"):
        retry_cleanup(row.pk, user)
    assert identity in module_store.objects and module_store.calls == []


@pytest.mark.django_db(transaction=True)
def test_absent_maker_rejects_privileged_restored_orphan_receipt_before_io(module_store):
    row, user = privileged_restored_orphan_receipt(), actor()
    key = f"staging/event/{row.source_makerspace_id}/{H}.png"
    identity = module_store.put(bucket_name("public_image"), key)
    original = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    with pytest.raises(Makerspace.DoesNotExist):
        retry_cleanup(row.pk, user)
    assert identity in module_store.objects and module_store.calls == []
    assert ModulePurgeReceipt.objects.values().get(pk=row.pk) == original


@pytest.mark.django_db
def test_manual_service_requires_uuid_and_atomic_caller_refuses_before_storage(module_store):
    space, user = module_space(), actor()
    with pytest.raises(ValidationError, match="canonical receipt UUID"):
        retry_cleanup(str(uuid4()), user)
    # This test deliberately retains pytest's application atomic wrapper.
    with pytest.raises(ValidationError, match="non-transactional"):
        purge_module(space, "events", user)
    assert module_store.calls == [] and not ModulePurgeReceipt.objects.exists()
