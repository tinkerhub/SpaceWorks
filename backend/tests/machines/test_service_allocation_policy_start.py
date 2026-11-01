"""Real start routes obey stored policy, machine scope, and stock validation."""

from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.machines.models import (
    Machine, MachineConsumableAdjustment, MachineType, RoleMachineTypeScope, ServiceQueue,
)
from apps.machines.service_consumable_pools import create_pool
from apps.machines.service_workflow import submit
from tests.machines.public_service_helpers import service_lab
from tests.machines.test_role_machine_scope import make_scoped_manager
from tests.machines.test_start_pool_validation import accepted_job, snapshot
from tests.return_helpers import authenticated_client, make_space
from tests.test_machine_service_api import action_url


pytestmark = pytest.mark.django_db


def test_start_payload_cannot_override_staff_select_but_explicit_machine_still_works():
    space, actor, machine, row, client = accepted_job("allocation-no-override")
    pool = create_pool(space, actor, material="PLA", initial_grams="50", machine_type=machine.machine_type)
    row.queue.refresh_from_db()
    assert row.queue.allocation_policy == "staff_select"
    before = snapshot(space, row, machine)
    queue_before = ServiceQueue.objects.filter(pk=row.queue_id).values().get()
    payload = {"allocation_policy": "first_idle", "machine_id": None,
               "consumable_pool_id": pool.pk, "planned_grams": "12.50"}

    refused = client.post(action_url(row, "start"), payload, format="json")

    assert (refused.status_code, refused.data["code"]) == (409, "service_machine_unavailable")
    assert snapshot(space, row, machine) == before
    assert ServiceQueue.objects.filter(pk=row.queue_id).values().get() == queue_before

    started = client.post(action_url(row, "start"), {**payload, "machine_id": machine.pk}, format="json")

    assert started.status_code == 200, started.data
    assert started.data["allocation_policy"] == "staff_select"
    assert started.data["assigned_machine"]["id"] == machine.pk
    row.refresh_from_db(); machine.refresh_from_db(); pool.refresh_from_db()
    assert (row.status, row.assigned_machine_id, machine.status) == ("in_progress", machine.pk, "running")
    assert (row.reserved_grams, pool.remaining_grams) == (Decimal("12.50"), Decimal("37.50"))
    assert ServiceQueue.objects.filter(pk=row.queue_id).values().get() == queue_before


def test_first_idle_null_machine_starts_scoped_compatible_printer_and_reserves_stock(service_lab):
    space, requester, _, generic, printer = service_lab
    actor, role = make_scoped_manager("allocation-printer-manager", space)
    RoleMachineTypeScope.objects.create(role=role, machine_type=printer)
    busy = Machine.objects.get(makerspace=space, machine_type=printer)
    busy.status = Machine.Status.RUNNING
    busy.save(update_fields=["status"])
    wrong_type = Machine.objects.get(makerspace=space, machine_type=generic)
    foreign = Machine.objects.create(
        makerspace=make_space("allocation-foreign-printer"), machine_type=printer,
        name="Foreign idle printer", type_payload={"model": "P1S"},
    )
    compatible = Machine.objects.create(
        makerspace=space, machine_type=printer, name="Later idle printer", type_payload={"model": "P1S"},
    )
    assert max(busy.pk, wrong_type.pk, foreign.pk) < compatible.pk
    queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=printer, name="Automatic prints", allocation_policy="first_idle",
    )
    row = submit(
        queue, requester, actor=actor, title="Scoped automatic print", requester_name="Maker",
        contact_email=requester.email, contact_phone="123",
        capability_payload={"requested_material": "PLA", "requested_color": "Black", "quantity": 1},
    )
    pool = create_pool(space, actor, material="PLA", color="Black", initial_grams="50", machine_type=printer)
    client = authenticated_client(actor)
    accepted = client.post(action_url(row, "accept"), {"estimated_minutes": 20}, format="json")
    assert accepted.status_code == 200, accepted.data
    row.refresh_from_db()
    assert (row.status, row.assigned_machine_id) == ("accepted", None)

    started = client.post(action_url(row, "start"), {
        "machine_id": None, "consumable_pool_id": pool.pk, "planned_grams": "12.50",
    }, format="json")

    assert started.status_code == 200, started.data
    assert started.data["allocation_policy"] == "first_idle"
    assert started.data["assigned_machine"]["id"] == compatible.pk
    row.refresh_from_db(); pool.refresh_from_db(); compatible.refresh_from_db()
    assert (row.status, row.assigned_machine_id, row.run_consumable_pool_id) == ("in_progress", compatible.pk, pool.pk)
    assert compatible.status == Machine.Status.RUNNING
    assert (row.reserved_grams, pool.remaining_grams) == (Decimal("12.50"), Decimal("37.50"))
    for machine, expected in ((busy, "running"), (wrong_type, "idle"), (foreign, "idle")):
        machine.refresh_from_db()
        assert machine.status == expected
    adjustment = MachineConsumableAdjustment.objects.get(service_request=row, kind="reserve")
    assert adjustment.quantity_delta == Decimal("-12.50")
    for event in ("assigned", "started"):
        assert AuditLog.objects.filter(makerspace=space, target_id=str(row.pk), action=f"machine_service.{event}").count() == 1
    queue.refresh_from_db()
    assert queue.allocation_policy == "first_idle"


@pytest.mark.parametrize("refusal", ["foreign_pool", "wrong_type_pool", "foreign_machine"])
def test_first_idle_refusal_keeps_assignment_stock_policy_and_audit_unchanged(refusal):
    space, actor, machine, row, client = accepted_job(f"allocation-refuse-{refusal.replace('_', '-')}")
    queue = row.queue
    queue.allocation_policy = "first_idle"
    queue.save(update_fields=["allocation_policy"])
    foreign_space = make_space("allocation-refusal-foreign")
    foreign_type = MachineType.objects.create(makerspace=foreign_space, slug="foreign", name="Foreign")
    foreign_machine = Machine.objects.create(makerspace=foreign_space, machine_type=foreign_type, name="Foreign")
    pool_space, pool_type = space, machine.machine_type
    if refusal == "foreign_pool":
        pool_space, pool_type = foreign_space, foreign_type
    elif refusal == "wrong_type_pool":
        pool_type = MachineType.objects.create(makerspace=space, slug="other", name="Other type")
    pool = create_pool(pool_space, actor, material="PLA", initial_grams="50", machine_type=pool_type)
    before = snapshot(space, row, machine)
    queue_before = ServiceQueue.objects.filter(pk=queue.pk).values().get()
    foreign_before = Machine.objects.filter(pk=foreign_machine.pk).values().get()

    response = client.post(action_url(row, "start"), {
        "machine_id": foreign_machine.pk if refusal == "foreign_machine" else None,
        "consumable_pool_id": pool.pk, "planned_grams": "12.50",
    }, format="json")

    if refusal == "foreign_machine":
        assert (response.status_code, response.data["code"]) == (409, "service_machine_unavailable")
    else:
        assert response.status_code == 400, response.data
        if refusal == "foreign_pool":
            assert response.data["code"] == "service_consumption_invalid"
        else:
            assert "consumable_pool" in str(response.data)
    assert snapshot(space, row, machine) == before
    assert ServiceQueue.objects.filter(pk=queue.pk).values().get() == queue_before
    assert Machine.objects.filter(pk=foreign_machine.pk).values().get() == foreign_before
