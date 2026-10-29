import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.machines.models import (
    Machine,
    MachineConsumablePool,
    MachineServiceRequest,
    MachineType,
    ServiceQueue,
)
from apps.machines.printer_capabilities import PRINTER_CONFIG
from tests.member_submission import active_member_client
from tests.return_helpers import make_space


pytestmark = pytest.mark.django_db


def _pool(space, material, **overrides):
    values = {
        "makerspace": space,
        "material": material,
        "color": "Blue",
        "initial_grams": "100",
        "remaining_grams": "100",
    }
    values.update(overrides)
    return MachineConsumablePool.objects.create(**values)


def _public_pool_setup(slug):
    space = make_space(slug)
    printer_type, _ = MachineType.objects.get_or_create(
        makerspace=None,
        slug="3d_printer",
        defaults={
            "name": "3D Printer",
            "is_builtin": True,
            "capability_config": PRINTER_CONFIG,
        },
    )
    non_printer_type = MachineType.objects.create(
        makerspace=space, slug=f"{slug}-laser", name="Laser"
    )
    queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=printer_type, name="Public print queue"
    )
    public_printer = Machine.objects.create(makerspace=space, machine_type=printer_type,
                                            name="Published printer", is_public=True, type_payload={"model": "MK4"})
    private_printer = Machine.objects.create(makerspace=space, machine_type=printer_type,
                                             name="Private printer", is_public=False, type_payload={"model": "MK4"})
    laser = Machine.objects.create(makerspace=space, machine_type=non_printer_type,
                                   name="Published laser", is_public=True)
    retired_printer = Machine.objects.create(makerspace=space, machine_type=printer_type,
                                             name="Retired printer", is_public=True, is_active=False, type_payload={"model": "MK4"})
    foreign = make_space(f"{slug}-foreign")
    excluded = [
        _pool(foreign, "PLA", machine_type=printer_type),
        _pool(space, "PLA"),  # Legacy unbound stock is deliberately not public type stock.
        _pool(space, "PLA", machine=private_printer),
        _pool(space, "PLA", machine=laser),
        _pool(space, "PLA", machine=retired_printer),
        _pool(space, "Unknown", machine_type=printer_type),
        _pool(space, "PLA", color="Invisible", machine_type=printer_type),
        _pool(space, "PLA", machine_type=printer_type, remaining_grams="0"),
        _pool(space, "PLA", machine_type=printer_type, is_public=False),
        _pool(space, "PLA", machine_type=non_printer_type),
        _pool(space, "PLA", machine_type=printer_type, unit="milliliters"),
    ]
    included = [
        _pool(space, "PLA", machine_type=printer_type),
        _pool(space, "PETG", machine=public_printer),
    ]
    return space, queue, excluded, included


def test_public_pool_list_keeps_only_eligible_public_printer_gram_stock():
    space, _, excluded, included = _public_pool_setup("public-pool-list")

    response = APIClient().get(
        reverse("public-printer-service-pools", args=[space.slug])
    )

    assert response.status_code == 200
    listed_ids = {row["id"] for row in response.data}
    assert listed_ids == {pool.pk for pool in included}
    assert listed_ids.isdisjoint(pool.pk for pool in excluded)


def test_public_submit_rejects_forged_ids_for_every_ineligible_active_pool():
    space, queue, excluded, _ = _public_pool_setup("public-pool-forgery")
    _, client = active_member_client(space, "public-pool-forger")
    url = reverse("public-printer-service-request", args=[space.slug])

    for pool in excluded:
        cache.clear()  # Isolate pool validation from the real burst throttle.
        assert pool.is_active
        response = client.post(
            url,
            {
                "queue_id": queue.pk,
                "title": f"Forged pool {pool.pk}",
                "consumable_pool_id": pool.pk,
            },
            format="json",
        )

        assert response.status_code == 400
        assert "consumable_pool_id" in response.data

    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()


def test_type_catalog_and_typed_submission_share_the_safe_compatible_pool_choices():
    space, queue, excluded, included = _public_pool_setup("typed-public-stock")
    printer = queue.machine_type
    queue.delete()  # Public type intake must work before staff configure any queue.
    catalog = APIClient().get(reverse("public-machine-service-types", args=[space.slug]))
    assert catalog.status_code == 200
    type_row = next(row for row in catalog.data["results"] if row["id"] == printer.pk)
    assert {row["id"] for row in type_row["consumable_pools"]} == {pool.pk for pool in included}
    assert all(set(row) == {"id", "material", "color"} for row in type_row["consumable_pools"])
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    actor, client = active_member_client(space, "typed-stock-maker")
    url = reverse("public-machine-service-request-submit", args=[space.slug])
    for pool in excluded:
        cache.clear()
        invalid = client.post(url, {"machine_type_id": printer.pk, "title": "Forged stock",
                                    "consumable_pool_id": pool.pk}, format="json")
        assert invalid.status_code == 400 and "consumable_pool_id" in invalid.data
        assert not ServiceQueue.objects.filter(makerspace=space).exists()
    pool = included[1]
    response = client.post(url, {
        "machine_type_id": printer.pk, "title": "Enclosure", "consumable_pool_id": pool.pk,
        "project_brief": "Outdoor enclosure", "preferred_settings": {"notes": "Use supports"},
        "estimated_filament_grams": "12.50", "quantity": 3,
    }, format="json")
    assert response.status_code == 201, response.data
    row = MachineServiceRequest.objects.get(public_token=response.data["public_token"])
    assert row.requester_id == actor.pk and row.assigned_machine_id is None
    assert row.queue.machine_type_id == printer.pk
    assert row.capability_payload == {
        "requested_material": pool.material, "requested_color": pool.color, "quantity": 3,
        "project_brief": "Outdoor enclosure", "requested_consumable_pool": pool.pk,
        "preferred_settings": {"notes": "Use supports"}, "estimated_grams": "12.50",
    }
