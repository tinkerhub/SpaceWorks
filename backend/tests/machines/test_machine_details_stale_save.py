"""Saving details cannot undo a status, publicity or retirement change."""
import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.machines import services
from apps.machines.models import Machine, MachineType
from apps.machines.serializers_machines import MachineSerializer
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


@pytest.fixture
def machine_lab():
    space = make_space("stale-machine-save")
    actor = make_member("stale-machine-save", space)
    kind = MachineType.objects.create(makerspace=space, slug="stale-save-laser", name="Laser")
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Laser", is_public=True)
    return actor, machine


def test_serializer_loaded_before_workflow_changes_saves_only_editable_details(machine_lab):
    actor, machine = machine_lab
    serializer = MachineSerializer(machine, data={
        "name": "Renamed laser", "notes": "Lens cleaned", "location": "Bench 2",
        "status": "running", "is_public": True, "is_active": True,
    }, partial=True)
    assert serializer.is_valid(), serializer.errors
    # Another request changes workflow fields after the details object was fetched.
    services.set_status(Machine.objects.get(pk=machine.pk), actor, Machine.Status.OFFLINE)
    Machine.objects.filter(pk=machine.pk).update(is_public=False, is_active=False)
    saved = serializer.save()
    machine.refresh_from_db()
    assert (machine.status, machine.is_public, machine.is_active) == ("offline", False, False)
    assert (saved.status, saved.is_public, saved.is_active) == ("offline", False, False)
    assert (machine.name, machine.notes, machine.location) == ("Renamed laser", "Lens cleaned", "Bench 2")


def test_status_endpoint_after_get_persists_and_details_cannot_overwrite_it(machine_lab):
    actor, machine = machine_lab
    client = authenticated_client(actor)
    detail = reverse("admin-machine-detail", args=[machine.pk])
    assert client.get(detail).data["status"] == "idle"
    changed = client.post(reverse("admin-machine-set-status", args=[machine.pk]),
                          {"status": "maintenance"}, format="json")
    assert changed.status_code == 200
    assert changed.data["status"] == "maintenance"
    response = client.patch(detail, {"name": "Serviced laser", "status": "idle",
                                     "is_active": False, "is_public": False}, format="json")
    assert response.status_code == 200, response.data
    machine.refresh_from_db()
    assert (machine.status, machine.is_public, machine.is_active) == ("maintenance", True, True)
    assert machine.name == "Serviced laser"
    event = AuditLog.objects.get(makerspace=machine.makerspace, action="machine.status_changed")
    assert event.actor == actor
    assert event.meta == {"old": "idle", "new": "maintenance"}
    assert client.get(detail).data["status"] == "maintenance"
