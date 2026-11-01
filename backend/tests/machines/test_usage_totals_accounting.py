"""Elapsed runs and append-only manual hours form two independent sources."""

from decimal import Decimal

import pytest

from apps.machines import service_workflow as workflow, services
from apps.machines.models import Machine
from apps.machines.usage_totals import annotate_machine_usage
from apps.operations import reports
from tests.machines.usage_totals_helpers import (
    historical_job, ledger_entry, sibling, started_job, submitted_job,
    terminal_job, usage_setup,
)


pytestmark = pytest.mark.django_db


def assert_hours(machine, expected):
    annotated = annotate_machine_usage(
        Machine.objects.filter(pk=machine.pk, makerspace_id=machine.makerspace_id),
    ).get()
    assert isinstance(annotated.usage_total, Decimal)
    assert annotated.usage_total == Decimal(expected)
    assert services.machine_usage_total(machine) == Decimal(expected)


@pytest.mark.parametrize("status", ["pending", "accepted", "in_progress", "rejected"])
def test_nonterminal_and_rejected_stale_actuals_never_own_linked_manual_hours(status):
    _space, actor, machine = usage_setup(f"usage-stale-{status}")
    if status == "in_progress":
        job = started_job(machine, actor)
    else:
        job = submitted_job(machine, actor)
        if status == "accepted":
            workflow.accept(job, actor, estimated_minutes=900)
        elif status == "rejected":
            workflow.reject(job, actor, reason="Unsuitable")
        job.refresh_from_db()
    # Historical stale measurements are non-status fields; keep the real edge
    # transitions and their guard intact while arranging this legacy fact.
    job.actual_minutes = 480
    job.assigned_machine = machine
    job.save(update_fields=["actual_minutes", "assigned_machine"])
    ledger_entry(machine, "1.25", job=job)
    assert job.status == status
    assert_hours(machine, "1.25")


@pytest.mark.parametrize("outcome", ["completed", "collected", "failed"])
def test_zero_actual_terminal_preserves_linked_manual_fallback(outcome):
    space, actor, machine = usage_setup(f"usage-zero-{outcome}")
    job = terminal_job(machine, actor, minutes=0, outcome=outcome)
    assert job.estimated_minutes == 10
    ledger_entry(machine, "0.75", job=job)
    ledger_entry(machine, "0.25")
    assert_hours(machine, "1.00")
    row = reports.report_data("machine-usage", space.pk)["typed_rows"][0]
    assert row["usage_entries"] == 2 and row["usage_hours"] == "1.00"


@pytest.mark.parametrize("outcome", ["completed", "collected", "failed"])
def test_positive_terminal_suppresses_all_matching_links_but_keeps_manual_count(outcome):
    space, actor, machine = usage_setup(f"usage-linked-{outcome}")
    job = terminal_job(machine, actor, outcome=outcome)
    first = ledger_entry(machine, "12.00", job=job)
    second = ledger_entry(machine, "12.00", job=job)
    independent = ledger_entry(machine, "0.25")
    assert_hours(machine, "0.38")
    row = reports.report_data("machine-usage", space.pk)["typed_rows"][0]
    assert row["usage_hours"] == "0.38"
    # Count is the manual ledger's row count, even when hours are deduplicated.
    assert row["usage_entries"] == 3
    assert set(machine.usage_entries.values_list("pk", flat=True)) == {
        first.pk, second.pk, independent.pk,
    }
    assert list(machine.usage_entries.order_by("pk").values_list("hours", flat=True)) == [
        Decimal("12.00"), Decimal("12.00"), Decimal("0.25"),
    ]


def test_link_to_a_run_assigned_to_another_machine_keeps_manual_fallback():
    _space, actor, machine = usage_setup("usage-other-machine")
    assigned = sibling(machine)
    job = terminal_job(assigned, actor)
    ledger_entry(machine, "0.75", job=job)
    assert_hours(machine, "0.75")
    assert_hours(assigned, "0.13")


def test_foreign_makerspace_run_cannot_own_current_machine_actuals_or_ledger():
    _space, actor, machine = usage_setup("usage-foreign-actual")
    foreign_space, _foreign_actor, foreign_machine = usage_setup("usage-foreign-owner")
    # Legacy corruption: request maker disagrees with its assigned hardware.
    job = historical_job(
        machine, actor, makerspace=foreign_space, status="completed", actual_minutes=600,
    )
    ledger_entry(machine, "0.75", job=job)
    assert_hours(machine, "0.75")
    assert_hours(foreign_machine, "0.00")


def test_foreign_request_link_does_not_suppress_local_manual_hours():
    _space, _actor, machine = usage_setup("usage-foreign-link")
    _foreign_space, foreign_actor, foreign_machine = usage_setup("usage-foreign-run")
    job = terminal_job(foreign_machine, foreign_actor, minutes=60)
    # The ledger link is a constructor-only historical cross-tenant corruption.
    ledger_entry(machine, "0.75", job=job)
    assert_hours(machine, "0.75")
    assert_hours(foreign_machine, "1.00")


def test_equal_duration_distinct_runs_and_ledgers_count_without_join_fanout():
    space, actor, machine = usage_setup("usage-independent-sums")
    for _ in range(3):
        terminal_job(machine, actor, minutes=30)
    for _ in range(2):
        ledger_entry(machine, "0.50")
    assert_hours(machine, "2.50")
    row = reports.report_data("machine-usage", space.pk)["typed_rows"][0]
    assert row["usage_entries"] == 2
    assert row["usage_hours"] == "2.50"


def test_annotating_many_populated_machines_requires_one_read(django_assert_num_queries):
    space, actor, first = usage_setup("usage-single-read")
    machines = [first, sibling(first, "Second"), sibling(first, "Third")]
    for machine in machines:
        terminal_job(machine, actor, minutes=30)
        ledger_entry(machine, "0.50")
    queryset = annotate_machine_usage(Machine.objects.filter(makerspace=space))
    with django_assert_num_queries(1):
        totals = {machine.pk: machine.usage_total for machine in queryset}
    assert totals == {machine.pk: Decimal("1.00") for machine in machines}


def test_empty_and_filtered_querysets_never_expand_to_other_machines():
    space, actor, machine = usage_setup("usage-empty-queryset")
    terminal_job(machine, actor, minutes=60)
    ledger_entry(machine, "2.00")
    assert list(annotate_machine_usage(Machine.objects.none())) == []
    assert list(annotate_machine_usage(
        Machine.objects.filter(makerspace=space).exclude(pk=machine.pk),
    )) == []
    assert list(annotate_machine_usage(
        Machine.objects.filter(makerspace=space, pk=machine.pk),
    ).values_list("pk", "usage_total")) == [(machine.pk, Decimal("3.00"))]
