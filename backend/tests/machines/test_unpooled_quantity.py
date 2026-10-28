"""A non-minute type that uses no consumables still measures, and is priced on, a quantity."""

from decimal import Decimal

import pytest

from apps.machines import role_scope
from apps.machines.models import Machine, MachineConsumableAdjustment, MachineType, MakerspaceMachineTypePricing
from apps.machines.service_pricing import compute_amount
from apps.machines.service_workflow import accept, complete, start, submit
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import core_module_keys, with_dependencies
from tests.return_helpers import authenticated_client, make_member

pytestmark = pytest.mark.django_db


def _priced_count_type(slug):
    modules = frozenset(core_module_keys()) | {"machines", "machine_service"}
    space = Makerspace.objects.create(name=slug, slug=slug, enabled_modules=sorted(with_dependencies(modules)))
    kind = MachineType.objects.create(
        makerspace=space, slug=f"{slug}-badges", name="Badges",
        capability_config={"metering_unit": "count", "requires_booking": False, "uses_consumables": False},
    )
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Press")
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space, machine_type=kind, rate_per_unit=Decimal("2.50"), flat_fee=Decimal("1.00"), payment_enabled=True,
    )
    return space, machine


def test_manual_usage_logs_and_prices_a_quantity_without_a_pool():
    space, machine = _priced_count_type("unpooled-manual")
    manager = make_member("unpooled-manual-sm", space)
    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspaces/{space.pk}/machine-service/typed-manual-usage",
        {"machine_id": machine.pk, "duration_minutes": 10, "outcome": "success", "quantity": "3", "metering_unit": "count"},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert (response.data["consumable_pool_id"], response.data["metering_unit"]) == (None, "count")
    assert (response.data["consumed_quantity"], response.data["price"]) == ("3.00", "8.50")  # 2.50 x 3 + 1.00
    assert not MachineConsumableAdjustment.objects.exists()


def test_manual_usage_without_a_pool_refuses_a_quantity_in_another_unit():
    space, machine = _priced_count_type("unpooled-unit")
    manager = make_member("unpooled-unit-sm", space)
    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspaces/{space.pk}/machine-service/typed-manual-usage",
        {"machine_id": machine.pk, "duration_minutes": 10, "outcome": "success", "quantity": "3", "metering_unit": "weight", "price": "0"},
        format="json",
    )
    assert response.status_code == 400


def test_job_plans_and_completes_a_quantity_without_a_pool_and_prices_it():
    space, machine = _priced_count_type("unpooled-job")
    manager = make_member("unpooled-job-sm", space)
    job = submit(machine, manager, actor=manager, requester_name="R", contact_email="r@test", contact_phone="1", title="Badges")
    accept(job, manager)
    started = start(job, manager, role_scope.EXEMPT, machine_id=machine.pk, planned_quantity="4")
    assert (started.metering_unit, started.planned_quantity, started.run_consumable_pool_id) == ("count", Decimal("4.00"), None)
    complete(job, manager, actual_minutes=5, consumptions=[], actual_quantity="3")
    job.refresh_from_db()
    assert job.actual_consumed_quantity == Decimal("3.00")
    assert compute_amount(job) == Decimal("8.50")
    assert not MachineConsumableAdjustment.objects.exists()
