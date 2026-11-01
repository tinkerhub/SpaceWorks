"""Reports use source event times and globally deduplicate before windowing."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.machines.models import Machine
from apps.machines.usage_totals import annotate_machine_usage
from apps.operations import reports
from tests.machines.usage_totals_helpers import ledger_entry, terminal_job, usage_setup


pytestmark = pytest.mark.django_db
START = datetime(2026, 3, 10, tzinfo=UTC)
END = START + timedelta(days=1)
WINDOW = (START, END)


def set_event_time(job, when):
    # Historical event timestamps are ordinary mutable, non-status fields.
    # Preserve workflow transitions; never update an append-only ledger row.
    if job.status == "failed":
        job.failed_at = when
        # Deliberate decoy: a failed run must ignore completed_at entirely.
        job.completed_at = END if START <= when < END else START
        fields = ["failed_at", "completed_at"]
    else:
        job.completed_at = when
        fields = ["completed_at"]
        if job.status == "collected":
            job.collected_at = END + timedelta(days=1)
            fields.append("collected_at")
    job.save(update_fields=fields)


def assert_period(space, machine, expected, entries, date_range=WINDOW):
    value = annotate_machine_usage(
        Machine.objects.filter(pk=machine.pk, makerspace=space), date_range=date_range,
    ).get().usage_total
    assert isinstance(value, Decimal) and value == Decimal(expected)
    usage = reports.report_data(
        "machine-usage", space.pk, date_range=date_range,
    )["typed_rows"][0]
    assert usage["machine_id"] == machine.pk
    assert usage["usage_hours"] == expected
    assert usage["usage_entries"] == entries
    health = reports.report_data(
        "fablab-health", space.pk, date_range=date_range,
    )["typed_rows"][0]
    assert health["machines_available"] is True
    assert health["machines_usage_hours"] == expected


@pytest.mark.parametrize("source", ["manual", "completed", "collected", "failed"])
@pytest.mark.parametrize("when,expected", [
    pytest.param(START - timedelta(microseconds=1), "0.00", id="before-start"),
    pytest.param(START, "0.50", id="inclusive-start"),
    pytest.param(END - timedelta(microseconds=1), "0.50", id="before-end"),
    pytest.param(END, "0.00", id="exclusive-end"),
])
def test_each_source_uses_its_own_inclusive_start_exclusive_end(source, when, expected):
    space, actor, machine = usage_setup(f"usage-boundary-{source}")
    if source == "manual":
        entry = ledger_entry(machine, "0.50", created_at=when)
        entry.refresh_from_db()
        assert entry.created_at == when
    else:
        job = terminal_job(machine, actor, minutes=30, outcome=source)
        set_event_time(job, when)
    entries = int(source == "manual" and expected == "0.50")
    assert_period(space, machine, expected, entries)


@pytest.mark.parametrize("outcome", ["completed", "collected", "failed"])
@pytest.mark.parametrize("actual_inside", [False, True])
def test_linked_ledger_never_reappears_when_actual_and_ledger_cross_windows(outcome, actual_inside):
    space, actor, machine = usage_setup(f"usage-window-dedup-{outcome}-{actual_inside}")
    job = terminal_job(machine, actor, outcome=outcome)
    inside, outside = START, END
    set_event_time(job, inside if actual_inside else outside)
    ledger_time = outside if actual_inside else inside
    # Multiple legacy links are all the same run; neither may become a fallback
    # merely because the authoritative actual is in another reporting period.
    ledger_entry(machine, "5.00", job=job, created_at=ledger_time)
    ledger_entry(machine, "5.00", job=job, created_at=ledger_time)
    assert_period(
        space, machine, "0.13" if actual_inside else "0.00",
        entries=0 if actual_inside else 2,
    )
    lifetime = reports.report_data("machine-usage", space.pk)["typed_rows"][0]
    assert lifetime["usage_hours"] == "0.13"
    assert lifetime["usage_entries"] == 2


def test_manual_and_actual_windows_are_independent_for_unlinked_sources():
    space, actor, machine = usage_setup("usage-window-independent")
    inside = terminal_job(machine, actor, minutes=15)
    outside = terminal_job(machine, actor, minutes=120)
    set_event_time(inside, START)
    set_event_time(outside, END)
    ledger_entry(machine, "0.50", created_at=START)
    ledger_entry(machine, "7.00", created_at=END)
    assert_period(space, machine, "0.75", entries=1)


@pytest.mark.parametrize("date_range,expected,entries", [
    ((None, END), "1.50", 1),
    ((START, None), "2.50", 1),
    ((None, None), "3.50", 2),
])
def test_open_ended_periods_keep_only_the_supplied_boundary(date_range, expected, entries):
    space, actor, machine = usage_setup("usage-open-window")
    before = START - timedelta(days=1)
    job = terminal_job(machine, actor, minutes=30)
    set_event_time(job, START)
    ledger_entry(machine, "1.00", created_at=before)
    ledger_entry(machine, "2.00", created_at=END)
    assert_period(space, machine, expected, entries, date_range)


def test_zero_actual_link_retains_manual_fallback_in_its_ledger_period():
    space, actor, machine = usage_setup("usage-window-zero-link")
    job = terminal_job(machine, actor, minutes=0)
    set_event_time(job, END)
    ledger_entry(machine, "0.75", job=job, created_at=START)
    ledger_entry(machine, "1.00", created_at=END)
    assert_period(space, machine, "0.75", entries=1)
