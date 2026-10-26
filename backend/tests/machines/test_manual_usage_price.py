"""Manual machine usage logs a price (auto from pricing, or typed); nothing is charged."""

from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.machines.models import (
    Machine,
    MachineType,
    MachineUsageEntry,
    MakerspaceMachineTypePricing,
    RoleMachineScope,
    RoleMachineTypeScope,
)
from apps.machines.service_consumable_pools import create_pool
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.module_registry import core_module_keys, with_dependencies
from apps.payments.models import Payment
from tests.return_helpers import authenticated_client, make_member

pytestmark = pytest.mark.django_db


def _space(slug):
    # No payments module: a logged price must not depend on it.
    modules = frozenset(core_module_keys()) | {"machines", "machine_service"}
    return Makerspace.objects.create(name=slug, slug=slug, enabled_modules=sorted(with_dependencies(modules)))


def _lab(slug, *, rate="2.00"):
    space = _space(slug)
    manager = make_member(f"{slug}-sm", space)
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    printer = Machine.objects.create(makerspace=space, machine_type=printer_type, name="MK4", type_payload={"model": "MK4"})
    pool = create_pool(space, manager, machine=printer, material="PLA", color="Blue", initial_grams="1000")
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space, machine_type=printer_type, rate_per_unit=Decimal(rate), free_below_quantity=Decimal("20"),
    )
    return space, manager, printer, pool


def _log(space, actor, machine, pool=None, **extra):
    body = {"machine_id": machine.pk, "duration_minutes": 30, "outcome": "success", **extra}
    if pool is not None:
        body["consumable_pool_id"] = pool.pk
    return authenticated_client(actor).post(
        f"/api/v1/admin/makerspaces/{space.pk}/machine-service/typed-manual-usage", body, format="json",
    )


def test_under_twenty_grams_logs_free_and_twenty_is_priced():
    space, manager, printer, pool = _lab("mu-free")
    free = _log(space, manager, printer, pool, grams="19.99")
    priced = _log(space, manager, printer, pool, grams="20")
    assert (free.status_code, priced.status_code) == (201, 201), (free.data, priced.data)
    assert (free.data["price"], priced.data["price"]) == ("0.00", "40.00")
    assert MachineUsageEntry.objects.get(pk=priced.data["id"]).price == Decimal("40.00")
    # Logging only: no charge is raised anywhere.
    assert not Payment.objects.filter(makerspace=space).exists()


def test_free_threshold_is_configurable():
    space, manager, printer, pool = _lab("mu-threshold")
    MakerspaceMachineTypePricing.objects.filter(makerspace=space).update(free_below_quantity=Decimal("5"))
    assert _log(space, manager, printer, pool, grams="10").data["price"] == "20.00"


def test_typed_price_overrides_the_auto_price():
    space, manager, printer, pool = _lab("mu-typed")
    assert _log(space, manager, printer, pool, grams="5", price="7.50").data["price"] == "7.50"
    assert _log(space, manager, printer, pool, grams="50", price="0").data["price"] == "0.00"


def test_unpriced_type_logs_no_price():
    space, manager, printer, pool = _lab("mu-unpriced", rate="0.00")
    assert _log(space, manager, printer, pool, grams="50").data["price"] is None


def test_mismatched_unit_is_refused_before_anything_is_written():
    space, manager, printer, pool = _lab("mu-unit")
    response = _log(space, manager, printer, duration_minutes=10, metering_unit="volume")
    assert response.status_code == 400
    assert not MachineUsageEntry.objects.filter(machine=printer).exists()


def test_minute_metered_type_prices_duration_with_a_threshold_in_minutes():
    space = _space("mu-minutes")
    manager = make_member("mu-minutes-sm", space)
    laser_type = MachineType.objects.create(
        makerspace=space, slug="mu-laser", name="Laser",
        capability_config={"metering_unit": "minutes", "requires_booking": False},
    )
    laser = Machine.objects.create(makerspace=space, machine_type=laser_type, name="Laser 1")
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space, machine_type=laser_type, rate_per_unit=Decimal("1.00"), flat_fee=Decimal("5.00"),
        free_below_quantity=Decimal("10"),
    )
    assert _log(space, manager, laser, duration_minutes=9, metering_unit="minutes").data["price"] == "0.00"
    response = _log(space, manager, laser, duration_minutes=12, metering_unit="minutes")
    assert response.status_code == 201, response.data
    assert response.data["price"] == "17.00"


def test_list_returns_each_logged_price():
    space, manager, printer, pool = _lab("mu-list")
    _log(space, manager, printer, pool, grams="10")
    _log(space, manager, printer, pool, grams="25")
    rows = authenticated_client(manager).get(
        f"/api/v1/admin/makerspaces/{space.pk}/machine-service/typed-manual-usage?machine_type_id={printer.machine_type_id}"
    ).data
    assert sorted(row["price"] for row in rows) == ["0.00", "50.00"]


def _scoped_manager(space, username, machine_type):
    actor = User.objects.create_user(
        username=username, email=f"{username}@example.test",
        role=User.Role.REQUESTER, access_status=User.AccessStatus.ACTIVE,
    )
    role = MakerspaceRole.objects.create(
        makerspace=space, name=username, slug=username, granted_actions=[Action.MANAGE_MACHINES],
    )
    MakerspaceMembership.objects.create(
        user=actor, makerspace=space, role=MakerspaceMembership.Role.CUSTOM, assigned_role=role,
    )
    RoleMachineTypeScope.objects.create(role=role, machine_type=machine_type)
    return actor


def test_machine_staff_price_their_own_types_only():
    space, manager, printer, pool = _lab("mu-pricing")
    laser_type = MachineType.objects.create(
        makerspace=space, slug="mu-pricing-laser", name="Laser",
        capability_config={"metering_unit": "minutes", "requires_booking": False},
    )
    laser_only = _scoped_manager(space, "mu-pricing-laser", laser_type)
    printer_staff = _scoped_manager(space, "mu-pricing-printer", printer.machine_type)
    url = f"/api/v1/admin/makerspace/{space.pk}/machine-type-pricing"

    rows = authenticated_client(laser_only).get(url).data["results"]
    assert [(row["machine_type_id"], row["free_below_quantity"]) for row in rows] == [(laser_type.pk, "0.00")]
    body = {"rate_per_unit": "1.50", "flat_fee": "0", "payment_enabled": False, "free_below_quantity": "5"}
    saved = authenticated_client(laser_only).put(f"{url}/{laser_type.pk}", body, format="json")
    assert saved.status_code == 200 and saved.data["free_below_quantity"] == "5.00"
    # Another type's price is not theirs to see or change.
    assert authenticated_client(laser_only).put(f"{url}/{printer.machine_type_id}", body, format="json").status_code == 404

    printer_body = {"rate_per_unit": "3", "flat_fee": "0", "payment_enabled": False, "free_below_quantity": "25"}
    assert authenticated_client(printer_staff).put(f"{url}/{printer.machine_type_id}", printer_body, format="json").status_code == 200
    assert _log(space, manager, printer, pool, grams="24").data["price"] == "0.00"
    # Online payment stays a space-manager switch.
    denied = authenticated_client(printer_staff).put(
        f"{url}/{printer.machine_type_id}", {**printer_body, "payment_enabled": True}, format="json",
    )
    assert denied.status_code == 403
    allowed = authenticated_client(manager).put(
        f"{url}/{printer.machine_type_id}", {**printer_body, "payment_enabled": True}, format="json",
    )
    assert allowed.status_code == 200 and allowed.data["payment_enabled"] is True


def test_a_role_linked_to_one_machine_cannot_price_its_whole_type():
    space, manager, printer, pool = _lab("mu-one-machine")
    actor = _scoped_manager(space, "mu-one-machine-staff", printer.machine_type)
    RoleMachineTypeScope.objects.filter(role__slug="mu-one-machine-staff").delete()
    RoleMachineScope.objects.create(role=MakerspaceRole.objects.get(slug="mu-one-machine-staff"), machine=printer)
    url = f"/api/v1/admin/makerspace/{space.pk}/machine-type-pricing"
    assert authenticated_client(actor).get(url).data["results"] == []
    body = {"rate_per_unit": "0", "flat_fee": "0", "payment_enabled": False, "free_below_quantity": "0"}
    assert authenticated_client(actor).put(f"{url}/{printer.machine_type_id}", body, format="json").status_code == 404


def test_unpriced_types_start_free_under_twenty_grams_for_printers_only():
    space = _space("mu-defaults")
    manager = make_member("mu-defaults-sm", space)
    rows = authenticated_client(manager).get(f"/api/v1/admin/makerspace/{space.pk}/machine-type-pricing").data["results"]
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    laser_type = MachineType.objects.get(makerspace__isnull=True, slug="laser_cutter")
    by_type = {row["machine_type_id"]: row["free_below_quantity"] for row in rows}
    assert (by_type[printer_type.pk], by_type[laser_type.pk]) == ("20.00", "0.00")


def test_an_auto_price_too_large_to_store_is_a_validation_error():
    space, manager, printer, pool = _lab("mu-overflow", rate="99999999.99")
    response = _log(space, manager, printer, pool, grams="200")
    assert response.status_code == 400, response.data
    assert "price" in response.data
    assert not MachineUsageEntry.objects.filter(machine=printer).exists()
