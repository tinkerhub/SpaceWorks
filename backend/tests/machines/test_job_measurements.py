"""Machine job outcomes record what was measured, on the right machine, priced from it."""

from decimal import Decimal

import pytest

from apps.machines import role_scope
from apps.machines.models import Machine, MachineType, MakerspaceMachineTypePricing
from apps.machines.service_consumable_pools import correct_pool, create_pool
from apps.machines.service_errors import ServiceMachineUnavailable
from apps.machines.service_pricing import compute_amount
from apps.machines.service_workflow import accept, complete, fail, start, submit
from apps.procurement.models import ToBuyItem
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


def _type(space, slug, unit):
    return MachineType.objects.create(
        makerspace=space, slug=slug, name=slug.title(), capability_config={"metering_unit": unit, "requires_booking": False},
    )


def _started(space, machine, actor, **start_kwargs):
    job = submit(machine, actor, actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Job")
    accept(job, actor)
    start(job, actor, role_scope.EXEMPT, machine_id=machine.pk, **start_kwargs)
    return job


def test_unpooled_completion_keeps_the_measured_quantity_for_pricing():
    space, actor = make_space("job-unpooled"), make_user("job-unpooled-actor")
    kind = _type(space, "stickers", "count")
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Plotter")
    MakerspaceMachineTypePricing.objects.create(makerspace=space, machine_type=kind, rate_per_unit=Decimal("1.50"))
    job = _started(space, machine, actor)
    complete(job, actor, actual_minutes=5, consumptions=[], actual_quantity="4")
    job.refresh_from_db()
    assert (job.metering_unit, job.actual_consumed_quantity) == ("count", Decimal("4.00"))
    assert compute_amount(job) == Decimal("0.00")  # payment not enabled: nothing to charge
    MakerspaceMachineTypePricing.objects.filter(makerspace=space).update(payment_enabled=True)
    assert compute_amount(job) == Decimal("6.00")


def test_unpooled_minutes_job_still_prices_its_minutes():
    space, actor = make_space("job-minutes"), make_user("job-minutes-actor")
    kind = _type(space, "laser", "minutes")
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Laser")
    MakerspaceMachineTypePricing.objects.create(makerspace=space, machine_type=kind, rate_per_unit=Decimal("2.00"), payment_enabled=True)
    job = _started(space, machine, actor)
    fail(job, actor, reason="Stopped", percent_complete=50, actual_minutes=7, consumptions=[], actual_quantity="99")
    job.refresh_from_db()
    assert (job.metering_unit, job.actual_consumed_quantity, compute_amount(job)) == ("minutes", None, Decimal("14.00"))


def test_failed_weight_job_uses_the_generic_actual_quantity():
    space, actor = make_space("job-weight-fail"), make_user("job-weight-fail-actor")
    kind = _type(space, "extruder", "weight")
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Extruder")
    pool = create_pool(space, actor, material="Pellets", initial_grams="100", machine=machine)
    job = _started(space, machine, actor, consumable_pool_id=pool.pk, planned_grams="40")
    fail(job, actor, reason="Clog", percent_complete=50, actual_minutes=3, consumptions=[], actual_quantity="7")
    job.refresh_from_db()
    pool.refresh_from_db()
    assert (job.actual_consumed_grams, pool.remaining_grams) == (Decimal("7.00"), Decimal("93.00"))


def test_failed_count_job_defaults_to_whole_items():
    space, actor = make_space("job-count-fail"), make_user("job-count-fail-actor")
    kind = _type(space, "badges", "count")
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Badge press")
    pool = create_pool(space, actor, material="Blanks", initial_grams="10", machine=machine)
    job = _started(space, machine, actor, consumable_pool_id=pool.pk, planned_quantity="3")
    fail(job, actor, reason="Jam", percent_complete=50, actual_minutes=1, consumptions=[])
    job.refresh_from_db()
    pool.refresh_from_db()
    assert (job.actual_consumed_quantity, pool.remaining_grams) == (Decimal("2.00"), Decimal("8.00"))


def test_bucket_job_runs_only_on_a_machine_of_the_same_type():
    space, actor = make_space("job-bucket"), make_user("job-bucket-actor")
    laser, router = _type(space, "laser-b", "minutes"), _type(space, "router-b", "minutes")
    asked = Machine.objects.create(makerspace=space, machine_type=laser, name="Laser A")
    sibling = Machine.objects.create(makerspace=space, machine_type=laser, name="Laser B")
    other = Machine.objects.create(makerspace=space, machine_type=router, name="Router")
    job = submit(asked, actor, actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Cut")
    accept(job, actor)
    with pytest.raises(ServiceMachineUnavailable):
        start(job, actor, role_scope.EXEMPT, machine_id=other.pk)
    started = start(job, actor, role_scope.EXEMPT, machine_id=sibling.pk)
    assert started.assigned_machine_id == sibling.pk


def test_restock_items_are_named_for_the_stock_they_replace():
    space, actor = make_space("job-restock"), make_user("job-restock-actor")
    resin = MachineType.objects.get(makerspace__isnull=True, slug="resin_printer")
    vinyl = MachineType.objects.get(makerspace__isnull=True, slug="vinyl_cutter")
    resin_pool = create_pool(space, actor, material="Grey", initial_grams="100", low_threshold_grams="50", machine_type=resin)
    vinyl_pool = create_pool(space, actor, material="Gloss", color="Black", initial_grams="100", low_threshold_grams="50", machine_type=vinyl)
    correct_pool(resin_pool, actor, quantity_delta="-60", reason="Used")
    correct_pool(vinyl_pool, actor, quantity_delta="-60", reason="Used")
    assert ToBuyItem.objects.get(source_pool=resin_pool).name == "Resin restock: Grey"
    vinyl_item = ToBuyItem.objects.get(source_pool=vinyl_pool)
    assert (vinyl_item.name, vinyl_item.kind, vinyl_item.machine_type_id) == (
        "Vinyl Cutter restock: Gloss Black", ToBuyItem.Kind.PRINTING, vinyl.pk,
    )
