"""Public queue setup is an explicit, scoped and idempotent staff operation."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.machines.models import MachineType, ServiceQueue
from apps.machines.printer_capabilities import PRINTER_CONFIG
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


@pytest.fixture
def queue_lab():
    space = make_space("public-queue-setup")
    actor = make_member("public-queue-setup", space)
    printer, _ = MachineType.objects.get_or_create(makerspace=None, slug="3d_printer", defaults={
        "name": "3D printer", "is_builtin": True,
        "managing_action": "manage_printing", "capability_config": PRINTER_CONFIG,
    })
    return space, actor, printer, reverse("admin-machine-printer-queue", args=[space.pk])


def test_get_is_read_only_post_creates_once_and_public_list_sees_queue(queue_lab):
    space, actor, printer, url = queue_lab
    client = authenticated_client(actor)
    before = AuditLog.objects.count()
    for _ in range(2):
        response = client.get(url)
        assert response.status_code == 200
        assert response.data == {"enabled": False, "queue_id": None, "name": None}
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert AuditLog.objects.count() == before
    first = client.post(url, {}, format="json")
    second = client.post(url, {}, format="json")
    assert first.status_code == second.status_code == 200
    assert first.data == second.data == client.get(url).data
    queue = ServiceQueue.objects.get(makerspace=space)
    assert queue.machine_type == printer
    assert queue.name == "Public Requests" and queue.is_active
    assert AuditLog.objects.count() == before + 1
    event = AuditLog.objects.get(action="machine_service.public_queue_created", makerspace=space)
    assert event.actor == actor and event.target_id == str(queue.pk)
    public = APIClient().get(reverse("public-printer-service-queues", args=[space.slug]))
    assert public.status_code == 200
    assert [row["id"] for row in public.data] == [queue.pk]


def test_existing_active_queue_is_selected_without_mutating_configuration(queue_lab):
    space, actor, printer, url = queue_lab
    active = ServiceQueue.objects.create(makerspace=space, machine_type=printer,
                                        name="Workshop jobs", capacity=7, allocation_policy="first_idle")
    disabled = ServiceQueue.objects.create(makerspace=space, machine_type=printer,
                                          name="Public Requests", is_active=False, capacity=3)
    before = list(ServiceQueue.objects.filter(makerspace=space).order_by("pk").values())
    audit_count = AuditLog.objects.count()
    client = authenticated_client(actor)
    for response in (client.get(url), client.post(url, {}, format="json")):
        assert response.status_code == 200
        assert response.data == {"enabled": True, "queue_id": active.pk, "name": active.name}
    assert list(ServiceQueue.objects.filter(makerspace=space).order_by("pk").values()) == before
    disabled.refresh_from_db()
    assert not disabled.is_active
    assert AuditLog.objects.count() == audit_count


def test_only_disabled_canonical_queue_is_activated_preserving_settings(queue_lab):
    space, actor, printer, url = queue_lab
    canonical = ServiceQueue.objects.create(makerspace=space, machine_type=printer,
        name="Public Requests", is_active=False, capacity=11, allocation_policy="first_idle",
        description="Operator configuration")
    other = ServiceQueue.objects.create(makerspace=space, machine_type=printer,
        name="Private disabled queue", is_active=False)
    client = authenticated_client(actor)
    before = AuditLog.objects.count()
    assert client.get(url).data["enabled"] is False
    canonical.refresh_from_db()
    assert not canonical.is_active
    response = client.post(url, {}, format="json")
    assert response.status_code == 200 and response.data["queue_id"] == canonical.pk
    assert client.post(url, {}, format="json").data == response.data
    canonical.refresh_from_db()
    other.refresh_from_db()
    assert canonical.is_active and not other.is_active
    assert (canonical.name, canonical.capacity, canonical.allocation_policy, canonical.description) == (
        "Public Requests", 11, "first_idle", "Operator configuration")
    assert ServiceQueue.objects.filter(makerspace=space).count() == 2
    assert AuditLog.objects.count() == before + 1
    assert AuditLog.objects.filter(makerspace=space, action="machine_service.public_queue_activated").count() == 1


def test_same_name_local_type_conflict_refuses_without_writes(queue_lab):
    space, actor, _printer, url = queue_lab
    local = MachineType.objects.create(makerspace=space, slug="3d_printer", name="Local printer")
    conflict = ServiceQueue.objects.create(makerspace=space, machine_type=local,
                                          name="Public Requests", is_active=False, capacity=5)
    before = ServiceQueue.objects.filter(pk=conflict.pk).values().get()
    audit_count = AuditLog.objects.count()
    response = authenticated_client(actor).post(url, {}, format="json")
    assert response.status_code == 409
    assert response.data["code"] == "public_queue_name_conflict"
    assert ServiceQueue.objects.filter(pk=conflict.pk).values().get() == before
    assert ServiceQueue.objects.filter(makerspace=space).count() == 1
    assert AuditLog.objects.count() == audit_count


def test_setup_refuses_configuration_payload(queue_lab):
    space, actor, _printer, url = queue_lab
    before = AuditLog.objects.count()
    response = authenticated_client(actor).post(url, {"capacity": 99}, format="json")
    assert response.status_code == 400
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert AuditLog.objects.count() == before
