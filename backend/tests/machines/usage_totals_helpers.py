"""Fixtures for recorded-hour contracts; normal runs use the real queue workflow."""

from decimal import Decimal

from apps.machines import role_scope, service_workflow as workflow
from apps.machines.models import (
    Machine, MachineServiceRequest, MachineType, MachineUsageEntry, ServiceQueue,
)
from tests.return_helpers import make_member, make_space


def usage_setup(slug):
    space = make_space(slug)
    space.public_inventory_enabled = space.public_stats_enabled = True
    space.save(update_fields=["public_inventory_enabled", "public_stats_enabled"])
    actor = make_member(f"{slug}-staff", space)
    kind = MachineType.objects.create(
        makerspace=space, slug="recorded-minutes", name="Generic minutes",
        capability_config={"metering_unit": "minutes", "requires_booking": False},
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=kind, name="Public cutter", is_public=True,
    )
    return space, actor, machine


def sibling(machine, name="Second cutter", **kwargs):
    return Machine.objects.create(
        makerspace=machine.makerspace, machine_type=machine.machine_type,
        name=name, **kwargs,
    )


def queue_for(machine):
    return ServiceQueue.objects.get_or_create(
        makerspace=machine.makerspace, machine_type=machine.machine_type,
        name=f"Recorded minutes {machine.machine_type_id}",
    )[0]


def submitted_job(machine, actor):
    return workflow.submit(
        queue_for(machine), actor, actor=actor, requester_name="Usage requester",
        contact_email="usage@example.test", contact_phone="123", title="Cut panel",
    )


def started_job(machine, actor):
    job = submitted_job(machine, actor)
    workflow.accept(job, actor, estimated_minutes=10)
    job.refresh_from_db()
    workflow.start(job, actor, role_scope.EXEMPT, machine_id=machine.pk)
    job.refresh_from_db()
    return job


def terminal_job(machine, actor, *, minutes=8, outcome="completed"):
    job = started_job(machine, actor)
    if outcome == "failed":
        workflow.fail(
            job, actor, reason="Stopped", percent_complete=25,
            actual_minutes=minutes, consumptions=[],
        )
    else:
        workflow.complete(job, actor, actual_minutes=minutes, consumptions=[])
    # Transitions return locked instances; callers must use persisted state.
    job.refresh_from_db()
    if outcome == "collected":
        workflow.collect(job, actor)
        job.refresh_from_db()
    return job


def ledger_entry(machine, hours, *, job=None, created_at=None):
    entry = MachineUsageEntry(
        machine=machine, hours=Decimal(hours), service_request=job,
    )
    if created_at is None:
        entry.save()
    else:
        entry.created_at = created_at
        entry.save(preserve_created_at=True)
    return entry


def historical_job(machine, actor, *, makerspace=None, **facts):
    # Constructor-only legacy fixture: inconsistent tenant/assignment facts cannot
    # be produced by today's workflow. Never disable its status or ledger guards.
    return MachineServiceRequest.objects.create(
        queue=queue_for(machine), makerspace=makerspace or machine.makerspace,
        assigned_machine=machine, requester=actor, title="Historical run", **facts,
    )
