"""Start validates stock through the real scoped API and reservation service."""

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog
from apps.machines.models import (
    Machine, MachineConsumableAdjustment, MachineConsumablePool,
    MachineServiceRequest, MachineType, ServiceQueue, ServiceRequestConsumption,
)
from apps.machines.service_consumable_pools import create_pool, retire_pool
from apps.machines.service_workflow import submit
from tests.return_helpers import authenticated_client, make_member, make_space
from tests.test_machine_service_api import action_url


pytestmark = pytest.mark.django_db


def accepted_job(slug):
    space = make_space(slug)
    actor = make_member(f"{slug}-manager", space)
    kind = MachineType.objects.create(
        makerspace=space, name="Weight service", slug="weight-service",
        capability_config={"metering_unit": "weight", "requires_booking": False},
    )
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Idle")
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=kind, name="Jobs")
    row = submit(
        queue, actor, actor=actor, requester_name="Maker",
        contact_email=actor.email, contact_phone="123", title="Unassigned job",
    )
    client = authenticated_client(actor)
    response = client.post(action_url(row, "accept"), {"estimated_minutes": 10}, format="json")
    assert response.status_code == 200, response.data
    row.refresh_from_db()
    assert (row.status, row.assigned_machine_id) == ("accepted", None)
    return space, actor, machine, row, client


def snapshot(space, row, machine):
    return {
        "request": MachineServiceRequest.objects.filter(pk=row.pk).values().get(),
        "machine": Machine.objects.filter(pk=machine.pk).values().get(),
        "pools": list(MachineConsumablePool.objects.order_by("pk").values()),
        "adjustments": list(MachineConsumableAdjustment.objects.order_by("pk").values()),
        "consumptions": list(ServiceRequestConsumption.objects.order_by("pk").values()),
        "audits": list(AuditLog.objects.filter(makerspace=space).order_by("pk").values()),
    }


@pytest.mark.parametrize("pool_case", ["missing", "foreign", "wrong_type", "wrong_machine", "wrong_unit", "inactive"])
def test_invalid_pool_returns_400_without_assigning_or_consuming(
    pool_case, django_capture_on_commit_callbacks,
):
    space, actor, machine, row, client = accepted_job(f"start-pool-{pool_case}")
    pool_space, pool_type, pool_machine = space, machine.machine_type, None
    if pool_case == "foreign":
        pool_space = make_space("start-pool-foreign-owner")
        pool_type = MachineType.objects.create(makerspace=pool_space, name="Foreign", slug="foreign")
    elif pool_case == "wrong_type":
        pool_type = MachineType.objects.create(makerspace=space, name="Other", slug="other")
    elif pool_case == "wrong_machine":
        pool_machine = Machine.objects.create(makerspace=space, machine_type=pool_type, name="Other")
    elif pool_case == "wrong_unit":
        pool_type = None
    pool = create_pool(
        pool_space, actor, material="PLA", initial_grams="50",
        **({"machine": pool_machine} if pool_machine else {"machine_type": pool_type}),
        **({"unit": "milliliters"} if pool_case == "wrong_unit" else {}),
    )
    if pool_case == "inactive":
        retire_pool(pool, actor, reason="Retired before start")
    pool_id = pool.pk + 100000 if pool_case == "missing" else pool.pk
    before = snapshot(space, row, machine)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = client.post(action_url(row, "start"), {
            "machine_id": machine.pk, "consumable_pool_id": pool_id,
            ("planned_quantity" if pool_case == "wrong_unit" else "planned_grams"): "12.50",
        }, format="json")

    assert response.status_code == 400, response.data
    if pool_case in {"missing", "foreign"}:
        assert response.data["code"] == "service_consumption_invalid"
    else:
        assert "consumable_pool" in str(response.data)
    assert snapshot(space, row, machine) == before
    assert callbacks == []


def test_compatible_pool_is_reserved_once_by_start():
    space, actor, machine, row, client = accepted_job("start-pool-valid")
    pool = create_pool(space, actor, material="PLA", initial_grams="50", machine_type=machine.machine_type)

    response = client.post(action_url(row, "start"), {
        "machine_id": machine.pk, "consumable_pool_id": pool.pk, "planned_grams": "12.50",
    }, format="json")

    assert response.status_code == 200, response.data
    row.refresh_from_db(); pool.refresh_from_db(); machine.refresh_from_db()
    assert (row.status, row.assigned_machine_id, machine.status) == ("in_progress", machine.pk, Machine.Status.RUNNING)
    assert (row.run_consumable_pool_id, row.reserved_grams, pool.remaining_grams) == (
        pool.pk, Decimal("12.50"), Decimal("37.50"),
    )
    adjustment = MachineConsumableAdjustment.objects.get(service_request=row, kind="reserve")
    assert adjustment.quantity_delta == Decimal("-12.50")
    assert not ServiceRequestConsumption.objects.filter(service_request=row).exists()
    assert AuditLog.objects.filter(target_id=str(row.pk), action="machine_service.assigned").count() == 1
    assert AuditLog.objects.filter(target_id=str(row.pk), action="machine_service.started").count() == 1


def test_foreign_request_is_denied_before_any_pool_query():
    space, actor, machine, row, _client = accepted_job("start-pool-hidden-request")
    outsider = make_member("start-pool-outsider", make_space("start-pool-outsider"))
    pool = create_pool(space, actor, material="Private stock", initial_grams="50", machine=machine)
    before = snapshot(space, row, machine)

    with CaptureQueriesContext(connection) as queries:
        response = authenticated_client(outsider).post(action_url(row, "start"), {
            "machine_id": machine.pk, "consumable_pool_id": pool.pk, "planned_grams": "1",
        }, format="json")

    assert response.status_code == 404, response.data
    assert all(MachineConsumablePool._meta.db_table not in query["sql"] for query in queries)
    assert snapshot(space, row, machine) == before
