"""Real generic queue runs agree across staff, public and operations surfaces."""

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.machines import role_scope, service_workflow as workflow, services
from apps.operations import reports
from tests.machines.usage_totals_helpers import (
    ledger_entry, sibling, terminal_job, usage_setup,
)
from tests.return_helpers import authenticated_client


pytestmark = pytest.mark.django_db
PUBLIC_KEYS = {"name", "machine_type", "image_url", "status", "usage_hours"}


def assert_projections(space, actor, machine, expected):
    expected_decimal = Decimal(expected)
    fallback = services.machine_usage_total(machine)
    assert isinstance(fallback, Decimal)
    assert fallback == expected_decimal
    staff = authenticated_client(actor)
    detail = staff.get(reverse("admin-machine-detail", kwargs={"pk": machine.pk}))
    listing = staff.get(reverse("admin-machines", args=[space.pk]))
    assert detail.status_code == listing.status_code == 200
    listed = next(row for row in listing.data["results"] if row["id"] == machine.pk)
    for row in (detail.data, listed):
        assert isinstance(row["usage_hours"], Decimal)
        assert row["usage_hours"] == expected_decimal

    public = APIClient()
    listing = public.get(reverse("public-machines", args=[space.slug]))
    assert listing.status_code == 200
    row = next(row for row in listing.data["results"] if row["name"] == machine.name)
    assert set(row) == PUBLIC_KEYS
    assert set(row["machine_type"]) == {"id", "name", "icon"}
    assert isinstance(row["usage_hours"], str)
    assert row["usage_hours"] == expected
    stats = public.get(reverse("v1:public-makerspace-stats", args=[space.slug]))
    assert stats.status_code == 200
    assert set(stats.data["machines"]) == {"usage_hours"}
    assert isinstance(stats.data["machines"]["usage_hours"], float)
    assert Decimal(str(stats.data["machines"]["usage_hours"])) == expected_decimal

    usage = reports.report_data("machine-usage", space.pk)["typed_rows"]
    row = next(row for row in usage if row["machine_id"] == machine.pk)
    assert isinstance(row["usage_hours"], str)
    assert row["usage_hours"] == expected
    assert row["usage_entries"] == machine.usage_entries.count()
    for route, field in (
        ("analytics-machine-usage", "usage_hours"),
        ("analytics-fablab-health", "machines_usage_hours"),
    ):
        response = staff.get(reverse(route, args=[space.pk]))
        assert response.status_code == 200
        value = response.data["typed_rows"][0][field]
        assert isinstance(value, str)
        assert value == expected


@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_eight_actual_minutes_reach_all_consumers_without_a_ledger_write(outcome):
    space, actor, machine = usage_setup(f"usage-surfaces-{outcome}")
    job = terminal_job(machine, actor, outcome=outcome)
    assert job.queue_id is not None and job.bucket_id is None
    assert job.assigned_machine_id == machine.pk
    assert job.estimated_minutes == 10 and job.actual_minutes == 8
    assert job.metering_unit == "minutes"
    if outcome == "failed":
        assert job.fail_percent_complete == 25
    assert not machine.usage_entries.exists()
    assert_projections(space, actor, machine, "0.13")


def test_collection_is_one_run_and_reprint_counts_only_after_actual_completion():
    space, actor, machine = usage_setup("usage-reprint")
    job = terminal_job(machine, actor)
    assert services.machine_usage_total(machine) == Decimal("0.13")
    workflow.collect(job, actor)
    job.refresh_from_db()
    assert job.status == "collected"
    assert services.machine_usage_total(machine) == Decimal("0.13")
    child = workflow.create_reprint(job, actor)
    child.refresh_from_db()
    assert child.status == "accepted" and child.reprint_of_id == job.pk
    assert child.estimated_minutes == 10 and child.actual_minutes == 0
    assert services.machine_usage_total(machine) == Decimal("0.13")
    workflow.start(child, actor, role_scope.EXEMPT, machine_id=machine.pk)
    child.refresh_from_db()
    assert services.machine_usage_total(machine) == Decimal("0.13")
    workflow.complete(child, actor, actual_minutes=8, consumptions=[])
    child.refresh_from_db()
    assert child.status == "completed"
    assert_projections(space, actor, machine, "0.27")


def test_two_one_minute_runs_on_one_machine_round_after_summing_minutes():
    space, actor, machine = usage_setup("usage-round-runs")
    terminal_job(machine, actor, minutes=1)
    terminal_job(machine, actor, minutes=1)
    assert_projections(space, actor, machine, "0.03")


def test_manual_hours_and_subhour_runs_round_once_together():
    space, actor, machine = usage_setup("usage-round-manual")
    ledger_entry(machine, "0.01")
    terminal_job(machine, actor, minutes=1)
    terminal_job(machine, actor, minutes=1)
    assert_projections(space, actor, machine, "0.04")


def test_stats_and_health_sum_each_machines_rounded_display_total():
    space, actor, first = usage_setup("usage-round-machines")
    second = sibling(first, is_public=True)
    for machine in (first, second):
        terminal_job(machine, actor, minutes=1)
        assert services.machine_usage_total(machine) == Decimal("0.02")
    public = APIClient()
    listing = public.get(reverse("public-machines", args=[space.slug]))
    assert listing.status_code == 200
    assert len(listing.data["results"]) == 2
    assert [row["usage_hours"] for row in listing.data["results"]] == ["0.02", "0.02"]
    stats = public.get(reverse("v1:public-makerspace-stats", args=[space.slug]))
    assert stats.status_code == 200
    value = stats.data["machines"]["usage_hours"]
    assert isinstance(value, float) and Decimal(str(value)) == Decimal("0.04")
    usage = reports.report_data("machine-usage", space.pk)["typed_rows"]
    assert {row["machine_id"] for row in usage} == {first.pk, second.pk}
    assert [row["usage_hours"] for row in usage] == ["0.02", "0.02"]
    health = reports.report_data("fablab-health", space.pk)["typed_rows"][0]
    assert health["machines_available"] is True
    assert health["machines_usage_hours"] == "0.04"
