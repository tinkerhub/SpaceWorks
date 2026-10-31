"""Template inheritance composes; recurrence keeps real storage ownership."""
from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.events import services_series
from apps.events.models import Event
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage
from tests.atomic_publication.domain import bind_store
from tests.atomic_publication.store import png
from tests.events.test_series_inheritance_invariants import series_case
from tests.metadata_boundaries.helpers import (
    CallerRollback, account_images, assert_caller_rollback, no_storage, snapshot,
)

pytestmark = pytest.mark.django_db


def image_series(slug):
    space, actor, series, events = series_case(slug, published=False)
    series.image_key = f"event-series/{space.pk}/template.png"
    series.save(update_fields=["image_key"])
    for event in events:
        event.image_key = f"event/{space.pk}/occurrence-{event.pk}.png"
        event.save(update_fields=["image_key"])
    account_images(space)
    return space, actor, series, events


def test_template_metadata_inherits_under_outer_atomic_without_touching_existing_images(no_storage):
    space, actor, series, events = image_series("series-metadata-images")
    original_images = {event.pk: event.image_key for event in events}
    # A deliberate occurrence override remains independent of the template.
    Event.objects.filter(pk=events[0].pk).update(title="Special", series_override_fields=["title"])
    with transaction.atomic():
        updated, created, removed = services_series.update_series(
            series, actor=actor, title="Shared", description="Updated", capacity=4,
            registration_requires_approval=True,
        )
        assert updated.title == "Shared" and created == removed == []
        assert updated.image_key == series.image_key
        for event in Event.objects.filter(series=series):
            assert event.title == ("Special" if event.pk == events[0].pk else "Shared")
            assert event.image_key == original_images[event.pk]
            assert event.capacity == 4 and event.registration_requires_approval
            assert event.series_override_fields == (["title"] if event.pk == events[0].pk else [])
        space.refresh_from_db()
        assert space.storage_bytes_used == 231
        audit = AuditLog.objects.get(makerspace=space, action="event.series_updated")
        assert audit.meta["removed_ids"] == audit.meta["created_ids"] == []


def test_caller_rollback_reverts_series_occurrences_calendar_and_audit(no_storage):
    space, actor, series, _events = image_series("series-metadata-rollback")
    def check(result):
        updated, created, removed = result
        assert updated.title == "Rolled back" and created == removed == []
        assert set(Event.objects.filter(series=series).values_list("title", flat=True)) == {"Rolled back"}
        assert AuditLog.objects.filter(makerspace=space, action="event.series_updated").exists()
    assert_caller_rollback(space, lambda: services_series.update_series(
        series, actor=actor, title="Rolled back", capacity=5,
    ), check)


@pytest.mark.parametrize("field", sorted(services_series.RECURRENCE_FIELDS))
def test_recurrence_field_presence_even_equal_value_refuses_outer_atomic(field, no_storage):
    space, actor, series, _events = image_series("series-recurrence-presence")
    original = snapshot(space)
    with transaction.atomic(), pytest.raises(StorageUnavailable):
        services_series.update_series(series, actor=actor, **{field: getattr(series, field)})
    assert snapshot(space) == original


def test_unknown_template_field_is_still_invalid_and_leaves_no_writes(no_storage):
    space, actor, series, _events = image_series("series-unknown-field")
    original = snapshot(space)
    with transaction.atomic(), pytest.raises(ValidationError):
        services_series.update_series(series, actor=actor, arbitrary_field="Rejected")
    assert snapshot(space) == original


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("rollback", [False, True])
def test_real_recurrence_guard_cleans_versions_only_after_commit_and_rollback_keeps_metadata(rollback, monkeypatch):
    from apps.object_storage_lifecycle import StorageGuard
    from apps.makerspaces import limits

    space, actor, series, events = image_series("series-recurrence-cleanup")
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    space.resource_limit_overrides = {"storage": 100000}
    space.save(update_fields=["resource_limit_overrides"])
    store = bind_store(monkeypatch, public_image_storage)
    data = png()
    for key in [series.image_key, *[event.image_key for event in events]]:
        store.seed(key, data, "image/png")
        store.seed(key, data, "image/png")
    account_images(space, len(data) * (len(events) + 1))
    original, bytes_before = snapshot(space), dict(store.objects)
    versions_before = {key: dict(versions) for key, versions in store.versions.items()}
    # Observe a genuine guard verification after metadata deletion but before
    # commit. A failure rolls back SQL and drops all on_commit cleanup callbacks.
    real_verify = StorageGuard.verify
    observed = []
    def verify(guard, makerspace_id=None):
        result = real_verify(guard, makerspace_id)
        if not observed and not Event.objects.filter(pk=events[-1].pk).exists():
            observed.append(True)
            assert dict(store.objects) == bytes_before
            assert not any(name == "delete" for name, _params in store.calls)
            if rollback:
                raise CallerRollback
        return result
    monkeypatch.setattr(StorageGuard, "verify", verify)
    def change():
        return services_series.update_series(
            series, actor=actor, dtstart_local_date=series.dtstart_local_date + timedelta(days=7),
            effective_from=timezone.now(),
        )
    if rollback:
        with pytest.raises(CallerRollback):
            change()
        assert snapshot(space) == original
        assert store.objects == bytes_before and store.versions == versions_before
    else:
        _updated, created, removed = change()
        assert set(removed) == {event.pk for event in events} and len(created) == 3
        assert all(event.image_key not in store.objects and store.versions[event.image_key] == {} for event in events)
        assert series.image_key in store.objects
        deletes = [params for name, params in store.calls if name == "delete"]
        assert len(deletes) == 3
        assert all("VersionId" in obj for params in deletes for obj in params["Delete"]["Objects"])
        space.refresh_from_db()
        assert space.storage_bytes_used == len(data)
    assert observed == [True]
