"""D3 module gates outside inventory, part 1: catalogs, counters, report registry (E1-E4,
dashboard).

Each OFF assertion is paired with the same call while the module is ON, so the refusal
or omission is provably the module and not an unrelated precondition.
"""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.events.models import Event, EventOrganizer
from apps.integrations.models import NotificationPreference
from apps.integrations.notify import LifecyclePayload, notify_lifecycle
from apps.makerspaces.models import Makerspace, MakerspaceRole
from apps.makerspaces.module_registry import core_module_keys, with_dependencies
from apps.organizations.models import Organization, OrganizationMakerspace, OrganizationMembership


pytestmark = pytest.mark.django_db

CORE = frozenset(core_module_keys())


def _space(slug, *extra):
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=sorted(with_dependencies(CORE | set(extra)))
    )


def _superadmin(slug):
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


# --- E1: the cross-venue organized-events list --------------------------------------


def test_organized_events_list_drops_venues_without_the_events_module():
    on, off, home = _space("d3-org-on", "events"), _space("d3-org-off"), _space("d3-org-home")
    start = timezone.now() + timedelta(days=1)
    events = [
        Event.objects.create(
            makerspace=venue, title=venue.slug, starts_at=start, ends_at=start + timedelta(hours=1)
        )
        for venue in (on, off)
    ]
    organization = Organization.objects.create(name="Org", slug="d3-org")
    OrganizationMakerspace.objects.create(
        organization=organization, makerspace=home,
        relationship=OrganizationMakerspace.Relationship.AFFILIATE,
    )
    actor = User.objects.create_user(
        username="d3-org-actor", email="d3-org-actor@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    OrganizationMembership.objects.create(
        organization=organization, user=actor, granted_actions=[rbac.Action.MANAGE_EVENTS]
    )
    for event in events:
        EventOrganizer.objects.create(event=event, organization=organization)

    response = _client(actor).get("/api/v1/admin/organized-events/")

    assert response.status_code == 200, response.data
    assert [row["id"] for row in response.data["results"]] == [events[0].pk]


# --- E2: lifecycle fan-out --------------------------------------------------------


@pytest.mark.parametrize("enabled", [False, True])
def test_notify_lifecycle_sends_nothing_for_a_feature_whose_module_is_off(enabled):
    space = _space(f"d3-notify-{enabled}".lower(), *(["events"] if enabled else []))
    build = Mock(return_value=LifecyclePayload(text="Event published"))

    result = notify_lifecycle(space, feature="events", event="published", build=build, sync=True)

    assert build.called is enabled
    if not enabled:
        assert (result.scheduled, result.delivered_counts, result.failed_counts) == (False, {}, {})


# --- E3: notification rules ---------------------------------------------------------


def test_notification_rules_omit_features_and_streams_of_off_modules():
    space = _space("d3-rules-core")
    client = _client(_superadmin("d3-rules-admin"))
    url = f"/api/v1/admin/makerspace/{space.pk}/notification-rules"

    data = client.get(url).data
    refused = client.patch(
        url,
        {"preferences": [{"feature": "events", "channel": "email", "enabled": True}]},
        format="json",
    )

    assert {row["key"] for row in data["features"]} == {"hardware_requests"}
    assert {row["feature"] for row in data["preferences"]} == {"hardware_requests"}
    assert not {row["stream"] for row in data["catalog"]} & {"printing", "events", "bookings", "maintenance", "membership"}
    assert refused.status_code == 400
    assert not NotificationPreference.objects.filter(makerspace=space).exists()

    space.enabled_modules = sorted(with_dependencies(CORE | {"events"}))
    space.save(update_fields=["enabled_modules"])
    assert "events" in {row["key"] for row in client.get(url).data["features"]}


# --- E4: role capability catalog ----------------------------------------------------


def test_capability_catalog_hides_off_module_groups_but_keeps_held_actions():
    space = _space("d3-catalog")
    client = _client(_superadmin("d3-catalog-admin"))
    url = f"/api/v1/admin/makerspaces/{space.pk}/roles/capabilities"

    values = {row["value"] for row in client.get(url).data}
    assert not values & {"manage_events", "manage_bookings", "manage_printing", "manage_machines"}
    assert "view_inventory" in values

    # The seeded Space Manager role holds every action; editing it must still list the
    # grants of off modules so they can be seen and removed.
    space_manager = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    values = {row["value"] for row in client.get(url, {"role_id": space_manager.pk}).data}
    assert {"manage_events", "manage_bookings"} <= values

    legacy = MakerspaceRole.objects.create(
        makerspace=space, slug="legacy-events", name="Legacy events",
        granted_actions=[rbac.Action.MANAGE_EVENTS],
    )
    values = {row["value"] for row in client.get(url, {"role_id": legacy.pk}).data}
    assert "manage_events" in values
    assert "manage_bookings" not in values

    space.enabled_modules = sorted(with_dependencies(CORE | {"events"}))
    space.save(update_fields=["enabled_modules"])
    assert "manage_events" in {row["value"] for row in client.get(url).data}


# --- dashboard counters and report registry ----------------------------------------


def test_dashboard_omits_counters_of_off_modules():
    off = _space("d3-dash-off")
    on = _space("d3-dash-on", "printing", "stocktake", "maintenance", "payments", "machines")
    client = _client(_superadmin("d3-dash-admin"))
    gated = {"pending_prints", "active_prints", "prints_awaiting_collection",
             "stocktakes_awaiting_approval", "maintenance_overdue", "pending_payments"}

    off_keys = set(client.get(f"/api/v1/admin/makerspace/{off.pk}/dashboard").data)
    on_keys = set(client.get(f"/api/v1/admin/makerspace/{on.pk}/dashboard").data)

    assert not off_keys & gated
    assert "overdue_loans" in off_keys
    assert gated <= on_keys


def test_payment_reconciliation_report_requires_the_payments_module():
    space = _space("d3-report-payments", "reports")
    client = _client(_superadmin("d3-report-admin"))

    catalog = client.get(f"/api/v1/admin/makerspace/{space.pk}/reports/catalog").data["results"]
    entry = next(row for row in catalog if row["key"] == "payment-reconciliation")
    preview = client.get(f"/api/v1/admin/makerspace/{space.pk}/analytics/payment-reconciliation")

    assert entry["required_modules"] == ["payments"]
    assert entry["available"] is False
    assert preview.status_code == 400
