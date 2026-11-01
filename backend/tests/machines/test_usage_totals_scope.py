"""Recorded hours inherit the existing caller's privacy and makerspace scope."""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.rbac import Action
from apps.machines.models import RoleMachineScope
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.operations import reports
from tests.machines.usage_totals_helpers import (
    ledger_entry, sibling, terminal_job, usage_setup,
)
from tests.return_helpers import authenticated_client, make_space, make_user


pytestmark = pytest.mark.django_db


def test_public_excludes_private_retired_and_foreign_hours_staff_retains_own_history():
    space, actor, public = usage_setup("usage-visibility")
    private = sibling(public, "Private cutter")
    retired = sibling(public, "Retired cutter", is_public=True)
    terminal_job(public, actor)
    terminal_job(private, actor, minutes=60)
    terminal_job(retired, actor, minutes=120)
    ledger_entry(retired, "1.00")
    retired.is_active = False
    retired.status = "offline"
    retired.save(update_fields=["is_active", "status"])
    foreign_space, foreign_actor, foreign = usage_setup("usage-visibility-foreign")
    terminal_job(foreign, foreign_actor, minutes=600)
    client = APIClient()
    listing = client.get(reverse("public-machines", args=[space.slug]))
    stats = client.get(reverse("v1:public-makerspace-stats", args=[space.slug]))
    assert listing.status_code == stats.status_code == 200
    assert [(row["name"], row["usage_hours"]) for row in listing.data["results"]] == [
        (public.name, "0.13"),
    ]
    assert Decimal(str(stats.data["machines"]["usage_hours"])) == Decimal("0.13")
    staff = authenticated_client(actor)
    response = staff.get(reverse("admin-machines", args=[space.pk]))
    assert response.status_code == 200
    assert {row["id"]: row["usage_hours"] for row in response.data["results"]} == {
        public.pk: Decimal("0.13"), private.pk: Decimal("1.00"),
        retired.pk: Decimal("3.00"),
    }
    assert staff.get(reverse("admin-machine-detail", args=[foreign.pk])).status_code == 404
    assert staff.get(reverse("admin-machines", args=[foreign_space.pk])).status_code == 403
    for route in ("analytics-machine-usage", "analytics-fablab-health"):
        assert staff.get(reverse(route, args=[foreign_space.pk])).status_code == 404
    usage = reports.report_data("machine-usage", space.pk)["typed_rows"]
    assert {row["machine_id"]: row["usage_hours"] for row in usage} == {
        public.pk: "0.13", private.pk: "1.00", retired.pk: "3.00",
    }
    assert next(row for row in usage if row["machine_id"] == retired.pk)["is_active"] is False
    health = reports.report_data("fablab-health", space.pk)["typed_rows"][0]
    assert health["machines_available"] is True
    assert health["machines_active"] == 2
    assert health["machines_usage_hours"] == "4.13"


def test_annotation_preserves_exact_machine_role_scope_on_staff_list_and_detail():
    space, manager, allowed = usage_setup("usage-role-scope")
    denied = sibling(allowed)
    terminal_job(allowed, manager)
    terminal_job(denied, manager, minutes=600)
    role = MakerspaceRole.objects.create(
        makerspace=space, name="One cutter", slug="one-cutter",
        granted_actions=[Action.MANAGE_MACHINES],
    )
    RoleMachineScope.objects.create(role=role, machine=allowed)
    actor = make_user("usage-scoped-actor", access_status="active")
    MakerspaceMembership.objects.create(
        user=actor, makerspace=space, role=MakerspaceMembership.Role.MACHINE_MANAGER,
        assigned_role=role,
    )
    client = authenticated_client(actor)
    listing = client.get(reverse("admin-machines", args=[space.pk]))
    assert listing.status_code == 200
    assert [(row["id"], row["usage_hours"]) for row in listing.data["results"]] == [
        (allowed.pk, Decimal("0.13")),
    ]
    detail = client.get(reverse("admin-machine-detail", args=[allowed.pk]))
    assert detail.status_code == 200 and detail.data["usage_hours"] == Decimal("0.13")
    assert client.get(reverse("admin-machine-detail", args=[denied.pk])).status_code == 404


@pytest.mark.parametrize("exclusion", ["reports-off", "superadmin-opt-out", "archived", "inactive"])
def test_aggregate_reports_never_add_actual_hours_from_ineligible_makerspaces(exclusion):
    eligible, actor, machine = usage_setup("usage-report-eligible")
    terminal_job(machine, actor)
    excluded, other_actor, other_machine = usage_setup("usage-report-excluded")
    terminal_job(other_machine, other_actor, minutes=600)
    if exclusion == "reports-off":
        excluded.enabled_modules = [key for key in excluded.enabled_modules if key != "reports"]
        fields = ["enabled_modules"]
    elif exclusion == "superadmin-opt-out":
        excluded.superadmin_access_enabled = False
        fields = ["superadmin_access_enabled"]
    elif exclusion == "archived":
        excluded.archived_at = timezone.now()
        fields = ["archived_at"]
    else:
        excluded.lifecycle_state = "importing"
        fields = ["lifecycle_state"]
    excluded.save(update_fields=fields)
    for key, field in (("machine-usage", "usage_hours"), ("fablab-health", "machines_usage_hours")):
        rows = reports.report_data(key)["typed_rows"]
        assert {row["makerspace_id"] for row in rows} == {eligible.pk}
        assert rows[0][field] == "0.13"


def test_machine_module_off_keeps_aggregate_hours_out_and_health_section_disabled():
    eligible, actor, machine = usage_setup("usage-module-eligible")
    terminal_job(machine, actor)
    disabled, other_actor, other_machine = usage_setup("usage-module-disabled")
    terminal_job(other_machine, other_actor, minutes=600)
    disabled.enabled_modules = [key for key in disabled.enabled_modules if key != "machines"]
    disabled.save(update_fields=["enabled_modules"])
    usage = reports.report_data("machine-usage")["typed_rows"]
    assert {row["makerspace_id"] for row in usage} == {eligible.pk}
    assert usage[0]["usage_hours"] == "0.13"
    health = {
        row["makerspace_id"]: row for row in reports.report_data("fablab-health")["typed_rows"]
    }
    assert health[eligible.pk]["machines_usage_hours"] == "0.13"
    assert health[disabled.pk]["machines_enabled"] is False
    assert health[disabled.pk]["machines_available"] is False
    assert health[disabled.pk]["machines_usage_hours"] is None
    public = APIClient()
    assert public.get(reverse("public-machines", args=[disabled.slug])).status_code == 404
    stats = public.get(reverse("v1:public-makerspace-stats", args=[disabled.slug]))
    assert stats.status_code == 200 and stats.data["machines"] is None


def test_health_retains_a_makerspace_with_no_machines_as_zero_hours():
    empty = make_space("usage-empty-space")
    other, actor, machine = usage_setup("usage-nonempty-space")
    terminal_job(machine, actor, minutes=600)
    selected = reports.report_data("fablab-health", empty.pk)["typed_rows"][0]
    assert selected["machines_enabled"] is True
    assert selected["machines_available"] is True
    assert selected["machines_active"] == 0
    assert selected["machines_usage_hours"] == "0.00"
    rows = {row["makerspace_id"]: row for row in reports.report_data("fablab-health")["typed_rows"]}
    assert set(rows) == {empty.pk, other.pk}
    assert rows[empty.pk]["machines_active"] == 0
    assert rows[empty.pk]["machines_usage_hours"] == "0.00"
    assert rows[other.pk]["machines_usage_hours"] == "10.00"
    assert reports.report_data("machine-usage", empty.pk)["typed_rows"] == []
