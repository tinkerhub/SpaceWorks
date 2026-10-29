"""The public catalog is a read-only, paginated, safe type projection."""
import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.machines.models import Machine, MachineType, ServiceQueue
from tests.machines.public_service_helpers import endpoint, service_lab
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

TYPE_KEYS = {"id", "name", "icon", "is_printer", "file_policy", "materials", "colors", "consumable_pools"}


def test_catalog_paginates_stable_type_ids_without_initializing_queues(service_lab):
    space, _, _, generic, printer = service_lab
    # Same human-readable name is deliberately not an identity.
    printer.name = generic.name
    printer.save(update_fields=["name"])
    for i in range(25):
        kind = MachineType.objects.create(makerspace=space, slug=f"type-{i}", name=f"Type {i:02}")
        Machine.objects.create(makerspace=space, machine_type=kind, name=f"Tool {i}", is_public=True)
    before = AuditLog.objects.count()
    client = APIClient()
    first = client.get(endpoint(space, "types"))
    second = client.get(endpoint(space, "types"), {"page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == 27 and first.data["next"]
    assert len(first.data["results"]) == 24 and len(second.data["results"]) == 3
    rows = first.data["results"] + second.data["results"]
    assert len({row["id"] for row in rows}) == 27
    assert {generic.pk, printer.pk} <= {row["id"] for row in rows}
    repeated = client.get(endpoint(space, "types")).data["results"]
    assert [row["id"] for row in first.data["results"]] == [row["id"] for row in repeated]
    assert all(set(row) == TYPE_KEYS for row in rows)
    for row in rows:
        assert set(row["file_policy"]) == {"allowed_extensions", "allowed_mimes", "max_bytes"}
    by_id = {row["id"]: row for row in rows}
    assert by_id[printer.pk]["is_printer"] is True
    assert by_id[printer.pk]["materials"] == printer.capability_config["accepted_materials"]
    assert by_id[printer.pk]["colors"] == printer.capability_config["accepted_colours"]
    assert by_id[generic.pk]["materials"] == by_id[generic.pk]["colors"] == []
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert AuditLog.objects.count() == before


@pytest.mark.parametrize("state", ["idle", "running", "reserved", "offline", "maintenance", "private", "retired", "foreign"])
def test_type_eligibility_accepts_busy_proposals_but_excludes_unpublished_machines(service_lab, state):
    space, _, _, generic, _ = service_lab
    machine = Machine.objects.get(makerspace=space, machine_type=generic)
    if state == "private":
        machine.is_public = False
    elif state == "retired":
        machine.is_active = False
    elif state == "foreign":
        machine.makerspace = make_space("foreign-catalog")
    else:
        machine.status = state
    machine.save()
    response = APIClient().get(endpoint(space, "types"))
    assert response.status_code == 200
    assert (generic.pk in {row["id"] for row in response.data["results"]}) == (state in {"idle", "running", "reserved"})
    assert not ServiceQueue.objects.exists()


@pytest.mark.parametrize("gate", ["machines", "machine_service", "public_inventory_enabled", "printing"])
def test_catalog_respects_module_and_master_public_gates(service_lab, gate):
    space, _, _, generic, printer = service_lab
    if gate == "public_inventory_enabled":
        space.public_inventory_enabled = False
    else:
        space.enabled_modules.remove(gate)
        if gate == "machine_service":
            space.enabled_modules.remove("printing")
    space.save()
    response = APIClient().get(endpoint(space, "types"))
    if gate == "printing":
        assert response.status_code == 200
        assert {row["id"] for row in response.data["results"]} == {generic.pk}
        assert printer.pk not in {row["id"] for row in response.data["results"]}
    else:
        assert response.status_code == 404
    assert not ServiceQueue.objects.exists()
