"""Per-makerspace settings for built-in machine types, and the one resolver every reader uses."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.machines import role_scope
from apps.machines.metering import validate_type_config
from apps.machines.models import Machine, MachineType, MakerspaceMachineTypePricing
from apps.machines.service_consumable_pools import create_pool
from apps.machines.service_workflow import accept, start, submit
from apps.machines.type_settings import effective_type_config
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.module_registry import core_module_keys, with_dependencies
from tests.return_helpers import authenticated_client, make_member, make_user

pytestmark = pytest.mark.django_db


def _space(slug):
    modules = frozenset(core_module_keys()) | {"machines", "machine_service"}
    return Makerspace.objects.create(name=slug, slug=slug, enabled_modules=sorted(with_dependencies(modules)))


def _builtin(slug):
    return MachineType.objects.get(makerspace__isnull=True, slug=slug)


def _settings_url(space, machine_type):
    return f"/api/v1/admin/makerspace/{space.pk}/machine-types/{machine_type.pk}/settings"


def _put(actor, space, machine_type, body):
    return authenticated_client(actor).put(_settings_url(space, machine_type), body, format="json")


def test_unconfigured_builtins_now_name_their_unit():
    assert _builtin("cnc_mill").capability_config == {"metering_unit": "minutes", "requires_booking": True}
    assert _builtin("pcb_mill").capability_config == {"metering_unit": "minutes", "requires_booking": False}
    assert _builtin("other").capability_config == {"metering_unit": "minutes", "requires_booking": False}
    assert effective_type_config(_builtin("cnc_mill"), None)["uses_consumables"] is False


def test_a_priced_cnc_mill_logs_manual_usage_by_the_minute():
    space = _space("ovr-cnc")
    manager = make_member("ovr-cnc-sm", space)
    mill = Machine.objects.create(makerspace=space, machine_type=_builtin("cnc_mill"), name="Mill")
    MakerspaceMachineTypePricing.objects.create(makerspace=space, machine_type=mill.machine_type, rate_per_unit=Decimal("2.00"))
    url = f"/api/v1/admin/makerspaces/{space.pk}/machine-service/typed-manual-usage"
    for extra in ({}, {"metering_unit": "minutes"}):
        response = authenticated_client(manager).post(
            url, {"machine_id": mill.pk, "duration_minutes": 15, "outcome": "success", **extra}, format="json",
        )
        assert response.status_code == 201, response.data
        assert (response.data["price"], response.data["metering_unit"]) == ("30.00", "minutes")


def test_override_applies_to_one_makerspace_only_and_is_audited():
    space, other = _space("ovr-scope"), _space("ovr-scope-other")
    manager = make_member("ovr-scope-sm", space)
    laser = _builtin("laser_cutter")

    response = _put(manager, space, laser, {"metering_unit": "count", "requires_booking": False})
    assert response.status_code == 200, response.data
    assert response.data["effective_config"] == {
        "metering_unit": "count", "requires_booking": False, "uses_consumables": True, "overridden": True,
    }
    assert effective_type_config(laser, other.pk)["metering_unit"] == "minutes"
    laser.refresh_from_db()
    assert laser.capability_config["metering_unit"] == "minutes"  # the shared type is untouched

    listed = authenticated_client(manager).get(f"/api/v1/admin/makerspace/{space.pk}/machine-types").data
    row = next(item for item in listed if item["id"] == laser.pk)
    assert row["effective_config"]["metering_unit"] == "count"

    log = AuditLog.objects.get(action="machine_type.settings_overridden")
    assert log.makerspace_id == space.pk
    assert log.meta["old"] == {"metering_unit": "minutes", "requires_booking": True, "uses_consumables": False}
    assert log.meta["new"] == {"metering_unit": "count", "requires_booking": False, "uses_consumables": True}

    cleared = _put(manager, space, laser, {"metering_unit": None, "requires_booking": None})
    assert cleared.data["effective_config"]["metering_unit"] == "minutes"
    assert cleared.data["effective_config"]["overridden"] is False


def test_only_a_space_manager_overrides_and_only_built_ins():
    space = _space("ovr-perm")
    manager = make_member("ovr-perm-sm", space)
    machine_staff = make_member(
        "ovr-perm-mm", space, membership_role=MakerspaceMembership.Role.MACHINE_MANAGER, role=User.Role.REQUESTER,
    )
    assert _put(machine_staff, space, _builtin("laser_cutter"), {"requires_booking": False}).status_code == 403
    custom = MachineType.objects.create(
        makerspace=space, slug="ovr-custom", name="Custom", capability_config={"metering_unit": "count", "requires_booking": False},
    )
    assert _put(manager, space, custom, {"requires_booking": True}).status_code == 400
    assert _put(manager, space, _builtin("laser_cutter"), {}).status_code == 400
    assert _put(manager, space, _builtin("laser_cutter"), {"metering_unit": "furlongs"}).status_code == 400


def test_printer_keeps_weight_and_its_filament_pools():
    space = _space("ovr-printer")
    manager = make_member("ovr-printer-sm", space)
    printer = _builtin("3d_printer")
    assert _put(manager, space, printer, {"metering_unit": "minutes"}).status_code == 400
    assert _put(manager, space, printer, {"uses_consumables": False}).status_code == 400
    assert _put(manager, space, printer, {"requires_booking": True}).status_code == 200


def test_unit_change_is_refused_while_pools_or_jobs_are_in_flight():
    space = _space("ovr-guard")
    manager = make_member("ovr-guard-sm", space)
    vinyl = _builtin("vinyl_cutter")
    pool = create_pool(space, manager, material="Vinyl", initial_grams="100", machine_type=vinyl)
    assert pool.unit == "millimeters"  # derived from the type, not chosen
    refused = _put(manager, space, vinyl, {"metering_unit": "count"})
    assert refused.status_code == 400 and "metering_unit" in refused.data
    assert _put(manager, space, vinyl, {"uses_consumables": False}).status_code == 400
    assert not MakerspaceMachineTypePricing.objects.filter(makerspace=space, machine_type=vinyl).exclude(
        metering_unit_override=None
    ).exists()

    laser = _builtin("laser_cutter")
    machine = Machine.objects.create(makerspace=space, machine_type=laser, name="Laser")
    job = submit(machine, manager, actor=manager, requester_name="R", contact_email="r@test", contact_phone="1", title="Cut")
    accept(job, manager)
    start(job, manager, role_scope.EXEMPT, machine_id=machine.pk)
    refused = _put(manager, space, laser, {"metering_unit": "count"})
    assert refused.status_code == 400 and "in progress" in str(refused.data["metering_unit"])
    assert _put(manager, space, laser, {"requires_booking": False}).status_code == 200


def test_custom_type_unit_change_uses_the_same_guard():
    space = _space("ovr-custom-guard")
    manager = make_member("ovr-custom-guard-sm", space)
    custom = MachineType.objects.create(
        makerspace=space, slug="ovr-sticker", name="Sticker", capability_config={"metering_unit": "count", "requires_booking": False},
    )
    create_pool(space, manager, material="Sheets", initial_grams="10", machine_type=custom)
    response = authenticated_client(manager).patch(
        f"/api/v1/admin/makerspace/{space.pk}/machine-types/{custom.pk}",
        {"capability_config": {"metering_unit": "weight", "requires_booking": False}}, format="json",
    )
    assert response.status_code == 400
    custom.refresh_from_db()
    assert custom.capability_config["metering_unit"] == "count"


def test_overridden_unit_drives_manual_pricing_and_pool_units():
    space = _space("ovr-pricing")
    manager = make_member("ovr-pricing-sm", space)
    laser = _builtin("laser_cutter")
    assert _put(manager, space, laser, {"metering_unit": "count"}).status_code == 200
    MakerspaceMachineTypePricing.objects.filter(makerspace=space, machine_type=laser).update(rate_per_unit=Decimal("3.00"))
    machine = Machine.objects.create(makerspace=space, machine_type=laser, name="Laser")
    pool = create_pool(space, manager, material="Acrylic sheet", initial_grams="10", machine=machine)
    assert pool.unit == "count"
    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspaces/{space.pk}/machine-service/typed-manual-usage",
        {"machine_id": machine.pk, "duration_minutes": 40, "outcome": "success", "consumable_pool_id": pool.pk,
         "quantity": "2", "metering_unit": "count"}, format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["price"] == "6.00"


def test_pool_unit_must_match_the_type_and_types_without_consumables_get_none():
    space = _space("ovr-pools")
    actor = make_user("ovr-pools-actor")
    resin = _builtin("resin_printer")
    from rest_framework.exceptions import ValidationError as DRFValidationError
    with pytest.raises(DRFValidationError):
        create_pool(space, actor, material="Resin", initial_grams="10", machine_type=resin, unit="grams")
    assert create_pool(space, actor, material="Resin", initial_grams="10", machine_type=resin).unit == "milliliters"
    with pytest.raises(DRFValidationError):
        create_pool(space, actor, material="Wood", initial_grams="10", machine_type=_builtin("cnc_router"))
    no_stock = MachineType.objects.create(
        makerspace=space, slug="ovr-no-stock", name="No stock",
        capability_config={"metering_unit": "count", "requires_booking": False, "uses_consumables": False},
    )
    with pytest.raises(DRFValidationError):
        create_pool(space, actor, material="Parts", initial_grams="10", machine_type=no_stock)
    # Shared, unscoped stock still chooses its unit.
    assert create_pool(space, actor, material="Tape", initial_grams="10", unit="millimeters").unit == "millimeters"


def test_uses_consumables_must_be_a_boolean():
    validate_type_config({"metering_unit": "count", "requires_booking": False, "uses_consumables": False}, is_custom=True)
    with pytest.raises(ValidationError):
        validate_type_config({"metering_unit": "count", "requires_booking": False, "uses_consumables": "no"}, is_custom=True)


def test_pool_api_derives_the_unit_for_a_typed_pool_and_refuses_another():
    space = _space("ovr-pool-api")
    manager = make_member("ovr-pool-api-sm", space)
    url = f"/api/v1/admin/makerspaces/{space.pk}/machine-service/consumable-pools"
    vinyl = _builtin("vinyl_cutter")
    client = authenticated_client(manager)
    derived = client.post(url, {"machine_type_id": vinyl.pk, "material": "Vinyl", "quantity": "5000"}, format="json")
    assert derived.status_code == 201, derived.data
    assert derived.data["unit"] == "millimeters"
    wrong = client.post(url, {"machine_type_id": vinyl.pk, "material": "Vinyl", "quantity": "5", "unit": "grams"}, format="json")
    assert wrong.status_code == 400 and "unit" in wrong.data
    shared = client.post(url, {"material": "Tape", "quantity": "5"}, format="json")
    assert shared.data["unit"] == "grams"


def test_migration_keeps_weight_for_spaces_already_metering_an_unconfigured_builtin():
    import importlib

    from django.apps import apps

    migration = importlib.import_module("apps.machines.migrations.0024_machine_type_makerspace_overrides")
    mill = _builtin("cnc_mill")
    MachineType.objects.filter(pk=mill.pk).update(capability_config={})
    weighed = _space("mill-by-weight")
    untouched = _space("mill-unused")
    MakerspaceMachineTypePricing.objects.create(
        makerspace=weighed, machine_type=mill, rate_per_unit="2.00", free_below_quantity="20"
    )

    migration.name_the_unit_of_unconfigured_builtins(apps, None)

    row = MakerspaceMachineTypePricing.objects.get(makerspace=weighed, machine_type=mill)
    assert row.metering_unit_override == "weight"
    assert row.free_below_quantity == Decimal("20")
    assert effective_type_config(_builtin("cnc_mill"), weighed.pk)["metering_unit"] == "weight"
    assert effective_type_config(_builtin("cnc_mill"), untouched.pk)["metering_unit"] == "minutes"
    assert not MakerspaceMachineTypePricing.objects.filter(makerspace=untouched, machine_type=mill).exists()
