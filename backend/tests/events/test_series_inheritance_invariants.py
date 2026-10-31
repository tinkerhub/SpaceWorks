"""Inherited templates use occurrence validation, promotion and atomic rollback."""

from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from threading import Barrier
from unittest.mock import Mock

import pytest
from django.db import close_old_connections, connections
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.events import services, services_series
from apps.events.exceptions import CapacityConflict
from apps.events.models import Event, EventRegistration, EventSeries
from tests.events.test_event_series import client_for, make_manager, make_space


pytestmark = pytest.mark.django_db


def series_case(slug, *, capacity=1, approval=False, published=True):
    space = make_space(slug)
    actor = make_manager(space, f"{slug}-manager")
    series, created = services_series.create_series(
        makerspace=space, actor=actor, title="Inherited title", is_public=True,
        capacity=capacity, registration_requires_approval=approval,
        recurrence_timezone="UTC", dtstart_local_date=(timezone.now() + timedelta(days=1)).date(),
        dtstart_local_time=time(10), recurrence_rule="FREQ=DAILY;COUNT=3", duration_minutes=60,
    )
    assert len(created) == 3
    if published:
        services_series.publish_series(series, actor=actor)
    series.refresh_from_db()
    return space, actor, series, list(Event.objects.filter(series=series).order_by("pk"))


def register(event, number):
    return services.register(
        event, name=f"Attendee {number}", email=f"attendee-{number}@example.test", phone="123",
    )


def snapshot(space, series):
    return (
        EventSeries.objects.filter(pk=series.pk).values().get(),
        list(Event.objects.filter(series=series).order_by("pk").values()),
        list(EventRegistration.objects.filter(event__series=series).order_by("pk").values()),
        list(AuditLog.objects.filter(makerspace=space).order_by("pk").values()),
    )


def test_capacity_below_late_occurrence_occupancy_conflicts_and_rolls_back_everything():
    space, actor, series, events = series_case("series-cap-rollback", capacity=3)
    # Earlier occurrences are updated before the last occurrence rejects the new template.
    register(events[-1], 1)
    register(events[-1], 2)
    before = snapshot(space, series)

    response = client_for(actor).patch(
        reverse("admin-event-series-detail", kwargs={"pk": series.pk}),
        {"capacity": 1, "title": "Must roll back"}, format="json",
    )

    assert (response.status_code, response.data["code"]) == (409, "capacity_conflict")
    assert snapshot(space, series) == before


@pytest.mark.parametrize("capacity, promoted_count", [(2, 1), (0, 2)])
def test_inherited_capacity_promotes_fifo_once_without_creating_overrides(
    capacity, promoted_count, monkeypatch,
):
    space, actor, series, events = series_case(f"series-promote-{capacity}")
    first, *waiters = [register(events[0], number) for number in range(3)]
    assert first.status == "registered"
    assert [row.status for row in waiters] == ["waitlisted", "waitlisted"]
    notify = Mock(wraps=services.notify_event_lifecycle)
    monkeypatch.setattr(services, "notify_event_lifecycle", notify)

    services_series.update_series(series, actor=actor, capacity=capacity, title="New template")
    services_series.update_series(series, actor=actor, capacity=capacity, title="New template")

    for event in events:
        event.refresh_from_db()
        assert (event.capacity, event.title, event.series_override_fields) == (capacity, "New template", [])
    for index, row in enumerate(waiters):
        row.refresh_from_db()
        assert row.status == ("registered" if index < promoted_count else "waitlisted")
    promotions = AuditLog.objects.filter(makerspace=space, action="event.registration_promoted").order_by("pk")
    assert list(promotions.values_list("target_id", flat=True)) == [str(row.pk) for row in waiters[:promoted_count]]
    assert all(row.meta["promotion_mode"] == "automatic_fifo" for row in promotions)
    assert [(call.args[1], call.args[2]) for call in notify.call_args_list] == [
        ("registration_promoted", row.pk) for row in waiters[:promoted_count]
    ]


def test_approval_required_occurrences_never_auto_promote_on_unlimited_capacity(monkeypatch):
    space, actor, series, events = series_case("series-approval-capacity", approval=True)
    first, second, third = [register(events[0], number) for number in range(3)]
    services.approve_registration(first, actor=actor)
    services.approve_registration(second, actor=actor)
    # Leave the third pending; neither pending applications nor approved waiters auto-promote.
    notify = Mock(wraps=services.notify_event_lifecycle)
    monkeypatch.setattr(services, "notify_event_lifecycle", notify)

    services_series.update_series(series, actor=actor, capacity=0)

    second.refresh_from_db(); third.refresh_from_db()
    assert (second.status, third.status) == ("waitlisted", "pending_approval")
    assert not AuditLog.objects.filter(makerspace=space, action="event.registration_promoted").exists()
    notify.assert_not_called()
    for event in events:
        event.refresh_from_db()
        assert event.capacity == 0 and event.registration_requires_approval
        assert event.series_override_fields == []


def test_published_policy_toggle_conflicts_and_rolls_back_template_occurrences_and_audits():
    space, actor, series, _events = series_case("series-policy-rollback")
    before = snapshot(space, series)

    response = client_for(actor).patch(
        reverse("admin-event-series-detail", kwargs={"pk": series.pk}),
        {"registration_requires_approval": True, "capacity": 2, "title": "Rejected template"},
        format="json",
    )

    assert (response.status_code, response.data["code"]) == (409, "invalid_transition")
    assert snapshot(space, series) == before


def test_draft_policy_toggle_is_inherited_without_becoming_an_override():
    _space, actor, series, events = series_case("series-draft-policy", published=False)

    updated, _created, _removed = services_series.update_series(
        series, actor=actor, registration_requires_approval=True,
    )

    assert updated.registration_requires_approval
    for event in events:
        event.refresh_from_db()
        assert event.status == "draft" and event.registration_requires_approval
        assert event.series_override_fields == []


def test_explicit_capacity_policy_and_title_overrides_survive_template_updates():
    _space, actor, series, events = series_case("series-explicit-overrides", published=False)
    special = events[0]
    services.update_event(
        special, actor=actor, capacity=4, registration_requires_approval=False, title="Special session",
    )
    services_series.update_series(
        series, actor=actor, capacity=2, registration_requires_approval=True, title="Shared template",
    )
    services_series.publish_series(series, actor=actor)
    services_series.update_series(series, actor=actor, capacity=3, title="Published template")

    special.refresh_from_db()
    assert (special.capacity, special.registration_requires_approval, special.title) == (4, False, "Special session")
    assert set(special.series_override_fields) == {"capacity", "registration_requires_approval", "title"}
    for event in events[1:]:
        event.refresh_from_db()
        assert (event.capacity, event.registration_requires_approval, event.title) == (3, True, "Published template")
        assert event.series_override_fields == []


@pytest.mark.django_db(transaction=True)
def test_registration_and_template_reduction_cannot_oversubscribe():
    _space, actor, series, events = series_case("series-register-race", capacity=2)
    register(events[0], 1)
    barrier = Barrier(2, timeout=10)

    def edit_template():
        close_old_connections()
        try:
            barrier.wait()
            try:
                services_series.update_series(series, actor=actor, capacity=1)
                return "updated"
            except CapacityConflict:
                return "conflict"
        finally:
            connections.close_all()

    def register_last():
        close_old_connections()
        try:
            barrier.wait()
            return register(events[0], 2).status
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        editing, joining = executor.submit(edit_template), executor.submit(register_last)
        outcome, status = editing.result(timeout=30), joining.result(timeout=30)

    series.refresh_from_db(); events[0].refresh_from_db()
    occupancy = events[0].registrations.filter(status__in=["registered", "attended"]).count()
    assert occupancy <= events[0].capacity == series.capacity
    assert (outcome, status, series.capacity) in {("updated", "waitlisted", 1), ("conflict", "registered", 2)}
    assert all(event.capacity == series.capacity and event.series_override_fields == []
               for event in Event.objects.filter(series=series))
