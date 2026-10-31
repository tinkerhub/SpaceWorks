"""Series inheritance and event mutation keep existing domain lock order."""
from datetime import timedelta
from threading import Event as ThreadEvent

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.events import services, services_images, services_series_images
from apps.events.models import Event
from apps.events.serializers_public import PublicEventSerializer
from apps.inventory import public_image_storage as storage
from tests.atomic_publication.domain import bind_store, setup_machine
from tests.atomic_publication.store import png
from tests.atomic_publication.threading import workers
from tests.events.test_event_series import create_daily_series

pytestmark = pytest.mark.django_db(transaction=True)


def test_series_prefix_explicit_occurrence_override_blocks_claim_but_blank_inherits(monkeypatch):
    space, actor, _machine = setup_machine("atomic-series-override", monkeypatch)
    series, _ = create_daily_series(space, actor)
    occurrence = Event.objects.filter(series=series).first()
    assert occurrence is not None
    key, data = f"event-series/{space.pk}/retained.png", png()
    store = bind_store(monkeypatch, storage)
    store.seed(key, data, "image/png")
    Event.objects.filter(pk=occurrence.pk).update(image_key=key, series_override_fields=["image_key"])
    occurrence.refresh_from_db()
    audit_before = AuditLog.objects.count()
    with pytest.raises(ValidationError):
        services_series_images.update_image(series, actor, key)
    series.refresh_from_db()
    space.refresh_from_db()
    assert series.image_key == "" and occurrence.image_key == key
    assert space.storage_bytes_used == 0 and AuditLog.objects.count() == audit_before
    assert store.objects[key][0] == data
    # Ordinary inheritance has no independently stored key and can safely resolve
    # the series artwork without another ownership claim or storage charge.
    Event.objects.filter(pk=occurrence.pk).update(image_key="", series_override_fields=[])
    services_series_images.update_image(series, actor, key)
    occurrence.refresh_from_db()
    assert occurrence.image_key == ""
    assert PublicEventSerializer(occurrence).data["image_url"] == storage.public_url(key)
    space.refresh_from_db()
    assert space.storage_bytes_used == len(data)
    services_series_images.update_image(series, actor, key)
    space.refresh_from_db()
    assert space.storage_bytes_used == len(data)
    assert AuditLog.objects.filter(makerspace=space, action="event.series_image_updated").count() == 1


@pytest.mark.parametrize("first", ["ordinary", "image"])
def test_event_image_and_ordinary_mutation_coexist_without_sql_lock_inversion(first, monkeypatch):
    space, actor, _machine = setup_machine(f"atomic-event-order-{first}", monkeypatch)
    start = timezone.now() + timedelta(days=1)
    event = Event.objects.create(makerspace=space, title="Original", starts_at=start, ends_at=start + timedelta(hours=1))
    store = bind_store(monkeypatch, storage)
    key, data = f"event/{space.pk}/cover.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    locked, proceed = ThreadEvent(), ThreadEvent()
    record = audit.record
    paused_action = "event.updated" if first == "ordinary" else "event.image_updated"
    def pause(actor, action, **kwargs):
        if action == paused_action:
            locked.set()
            assert proceed.wait(4)
        return record(actor, action, **kwargs)
    monkeypatch.setattr(audit, "record", pause)
    ordinary = lambda: services.update_event(event, actor=actor, title="Changed")
    image = lambda: services_images.update_image(event, actor, key)
    operations = (ordinary, image) if first == "ordinary" else (image, ordinary)
    with workers() as spawn:
        first_result = spawn(operations[0])
        assert locked.wait(4)
        second_result = spawn(operations[1])
        try:
            assert not second_result.done()
        finally:
            proceed.set()
        first_result.result(timeout=8)
        second_result.result(timeout=8)
    event.refresh_from_db()
    space.refresh_from_db()
    assert event.title == "Changed" and event.image_key == key
    assert space.storage_bytes_used == len(data) and store.objects[key][0] == data
