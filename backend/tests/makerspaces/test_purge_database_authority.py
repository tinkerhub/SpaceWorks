"""Postgres protects irreversible intent and inert receipt authority below ORM."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.makerspaces.lifecycle_archive import unarchive
from apps.makerspaces.models import Makerspace, PurgeReceipt
from apps.makerspaces.purge_receipt_recovery import invalidate_restored_receipts
from apps.makerspaces.servability import is_servable, servable_queryset
from apps.tenant_migration.gate_runtime import assert_write_allowed, boundary_tenant_write, tenant_write
from apps.makerspaces.purge_intent import PurgeInProgress
from tests.makerspaces.purge_test_support import actor, archived_space, receipt

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("writer", ["stale_save", "save", "queryset", "bulk", "raw"])
@pytest.mark.parametrize("change", ["clear", "replace"])
def test_committed_intent_cannot_be_reset_by_any_writer(writer, change):
    space = archived_space()
    stale = Makerspace.objects.get(pk=space.pk)
    now = timezone.now()
    assert Makerspace.objects.filter(pk=space.pk).update(purge_started_at=now) == 1
    value = None if change == "clear" else now + timedelta(seconds=1)
    space.refresh_from_db()
    with pytest.raises((DatabaseError, ValidationError)):
        with transaction.atomic():
            if writer == "raw":
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE makerspaces_makerspace SET purge_started_at=%s WHERE id=%s", [value, space.pk])
            elif writer == "queryset":
                Makerspace.objects.filter(pk=space.pk).update(purge_started_at=value)
            elif writer == "bulk":
                space.purge_started_at = value
                Makerspace.objects.bulk_update([space], ["purge_started_at"])
            else:
                row = stale if writer == "stale_save" else space
                row.purge_started_at = value
                row.name = "stale fullsave"
                row.save()
    space.refresh_from_db()
    assert space.purge_started_at == now
    assert space.name != "stale fullsave"


def test_intent_requires_archived_row_and_does_not_prevent_graph_delete():
    space = Makerspace.objects.create(name="ordinary", slug="ordinary")
    source_id = space.pk
    assert space.purge_started_at is None
    with pytest.raises(DatabaseError), transaction.atomic():
        Makerspace.objects.filter(pk=space.pk).update(purge_started_at=timezone.now())
    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now(), purge_started_at=timezone.now())
    with pytest.raises(DatabaseError), transaction.atomic():
        Makerspace.objects.filter(pk=space.pk).update(archived_at=None)
    # Intent is a monotonic UPDATE guard, not an accidental DELETE prohibition.
    from apps.makerspaces.lifecycle_purge import _delete_object_graph

    with transaction.atomic():
        _delete_object_graph(space)
    assert not Makerspace.objects.filter(pk=source_id).exists()


def test_purge_intent_denies_unarchive_archived_override_and_common_write_paths():
    space, user = archived_space(), actor()
    Makerspace.objects.filter(pk=space.pk).update(purge_started_at=timezone.now())
    space.refresh_from_db()
    assert not is_servable(space, allow_archived=True)
    assert not servable_queryset().filter(pk=space.pk).exists()
    with pytest.raises(ValidationError, match="Purge has started"):
        unarchive(space, user)
    for boundary in (boundary_tenant_write, tenant_write):
        with pytest.raises(PurgeInProgress), boundary(space.pk):
            pytest.fail("purge-started source dispatched a writer")
    with pytest.raises(PurgeInProgress):
        assert_write_allowed(space.pk)


@pytest.mark.parametrize("writer", ["save", "queryset", "bulk", "raw"])
@pytest.mark.parametrize("field", ["source_makerspace_id", "source_purge_started_at", "auth_generation", "schema_version", "storage_origins", "namespace_prefixes", "exact_keys", "graph_purged_at"])
def test_receipt_authority_is_immutable_for_all_writers(writer, field):
    row = receipt()
    original = PurgeReceipt.objects.values().get(pk=row.pk)
    replacement = {
        "source_makerspace_id": row.source_makerspace_id - 1,
        "source_purge_started_at": row.source_purge_started_at + timedelta(seconds=1),
        "schema_version": 2, "storage_origins": {"private": "0" * 64, "public_image": "1" * 64},
        "auth_generation": uuid4(), "namespace_prefixes": [], "exact_keys": [["private", "bulk-imports/foreign"]],
        "graph_purged_at": row.graph_purged_at + timedelta(seconds=1),
    }[field]
    with pytest.raises((DatabaseError, ValidationError)), transaction.atomic():
        if writer == "raw":
            # Let Django adapt JSON/UUID values, then issue literal SQL below ORM guards.
            model_field = row._meta.get_field(field)
            value = model_field.get_db_prep_save(replacement, connection)
            with connection.cursor() as cursor:
                cursor.execute(f'UPDATE makerspaces_purgereceipt SET "{field}"=%s WHERE id=%s', [value, row.pk])
        elif writer == "queryset":
            PurgeReceipt.objects.filter(pk=row.pk).update(**{field: replacement})
        else:
            setattr(row, field, replacement)
            if writer == "bulk":
                PurgeReceipt.objects.bulk_update([row], [field])
            else:
                row.save()
    assert PurgeReceipt.objects.values().get(pk=row.pk) == original


def test_receipt_primary_key_cannot_be_rebound_by_raw_update():
    row = receipt()
    replacement = uuid4()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE makerspaces_purgereceipt SET id=%s WHERE id=%s", [replacement, row.pk])
    assert PurgeReceipt.objects.filter(pk=row.pk).exists()
    assert not PurgeReceipt.objects.filter(pk=replacement).exists()


@pytest.mark.parametrize("change", ["authority", "invalidation"])
def test_projection_delete_permission_does_not_force_receipt_update(change):
    row = receipt()
    invalidate_restored_receipts()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        if change == "authority":
            cursor.execute("UPDATE makerspaces_purgereceipt SET schema_version=2 WHERE id=%s", [row.pk])
        else:
            cursor.execute("UPDATE makerspaces_purgereceipt SET invalidated_at=NULL WHERE id=%s", [row.pk])
    row.refresh_from_db()
    assert row.schema_version == 1 and row.invalidated_at is not None


def test_receipt_status_mutable_invalidation_monotonic_and_no_foreign_keys():
    row = receipt()
    assert not any(field.is_relation for field in row._meta.concrete_fields)
    row.last_attempt_at = timezone.now()
    row.last_error_code = "cleanup_unconfirmed"
    row.save(update_fields=["last_attempt_at", "last_error_code"])
    assert invalidate_restored_receipts() == 1
    row.refresh_from_db()
    invalidated = row.invalidated_at
    assert invalidated is not None
    assert invalidate_restored_receipts() == 0
    for value in (None, invalidated + timedelta(seconds=1)):
        with pytest.raises(DatabaseError), transaction.atomic():
            PurgeReceipt.objects.filter(pk=row.pk).update(invalidated_at=value)
    with pytest.raises(ValidationError):
        row.invalidated_at = None
        row.save(force_update=True)
    with pytest.raises(DatabaseError), transaction.atomic():
        PurgeReceipt.objects.filter(pk=row.pk).update(last_error_code="success_guessed")
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM makerspaces_purgereceipt WHERE id=%s", [row.pk])
    row.refresh_from_db()
    assert row.invalidated_at == invalidated
    assert row.last_error_code == "cleanup_unconfirmed"
