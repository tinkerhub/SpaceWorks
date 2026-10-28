"""Queue permission must cover the global printer type, not merely one machine."""
import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.machines.models import Machine, MachineType, ServiceQueue
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.machines.test_machine_scope_authorization import _manager
from tests.machines.test_public_printer_queue_setup import queue_lab
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("authority", ["type", "unscoped"])
def test_full_type_or_space_management_can_enable_queue(queue_lab, authority):
    space, actor, printer, url = queue_lab
    if authority == "type":
        actor = _manager(space, "queue-eligible", machine_type=printer)
    client = authenticated_client(actor)
    assert client.get(url).status_code == 200
    assert client.post(url, {}, format="json").status_code == 200


@pytest.mark.parametrize("authority", ["machine_only", "wrong_type", "direct_type", "inactive", "restricted"])
def test_ineligible_staff_cannot_read_or_enable_queue(queue_lab, authority):
    space, actor, printer, url = queue_lab
    if authority == "machine_only":
        machine = Machine.objects.create(makerspace=space, machine_type=printer, name="One printer")
        actor = _manager(space, "queue-one-machine", machine=machine)
    elif authority == "wrong_type":
        local = MachineType.objects.create(makerspace=space, slug="laser", name="Laser")
        actor = _manager(space, "queue-wrong-type", machine_type=local)
    elif authority == "direct_type":
        actor = make_user("queue-direct-type")
        role = MakerspaceRole.objects.create(makerspace=space, name="Print jobs", slug="print-jobs",
                                              granted_actions=[printer.managing_action])
        MakerspaceMembership.objects.create(makerspace=space, user=actor, role="custom", assigned_role=role)
    elif authority == "inactive":
        actor.is_active = False
        actor.save(update_fields=["is_active"])
    else:
        actor.access_status = User.AccessStatus.RESTRICTED
        actor.save(update_fields=["access_status"])
    before = AuditLog.objects.count()
    client = authenticated_client(actor)
    assert client.get(url).status_code == 403
    assert client.post(url, {}, format="json").status_code == 403
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert AuditLog.objects.count() == before
    if authority in {"machine_only", "direct_type", "wrong_type"}:
        listed = client.get(reverse("admin-machine-types", args=[space.pk]))
        assert listed.status_code == 200
        assert not any(row.get("can_manage_public_queue", False) for row in listed.data)
        if authority != "wrong_type":
            assert printer.pk in {row["id"] for row in listed.data}


@pytest.mark.parametrize("target", ["unknown", "other_space"])
def test_queue_setup_does_not_expose_another_space(queue_lab, target):
    space, actor, _printer, _url = queue_lab
    other = make_space("queue-other-space")
    make_member("queue-other-manager", other)
    pk = other.pk if target == "other_space" else other.pk + space.pk + 10000
    url = reverse("admin-machine-printer-queue", args=[pk])
    before = AuditLog.objects.count()
    client = authenticated_client(actor)
    assert client.get(url).status_code == 404
    assert client.post(url, {}, format="json").status_code == 404
    assert not ServiceQueue.objects.exists()
    assert AuditLog.objects.count() == before


@pytest.mark.parametrize("module", ["machines", "machine_service", "printing"])
def test_queue_setup_requires_all_modules_for_reads_and_writes(queue_lab, module):
    space, actor, _printer, url = queue_lab
    space.enabled_modules = [key for key in space.enabled_modules if key != module]
    space.save(update_fields=["enabled_modules"])
    before = AuditLog.objects.count()
    client = authenticated_client(actor)
    assert client.get(url).status_code == 400
    assert client.post(url, {}, format="json").status_code == 400
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert AuditLog.objects.count() == before


def test_type_list_advertises_queue_setup_only_for_global_printer(queue_lab):
    space, actor, printer, _url = queue_lab
    local = MachineType.objects.create(makerspace=space, slug="3d_printer", name="Local printer")
    laser = MachineType.objects.create(makerspace=space, slug="laser", name="Laser")
    url = reverse("admin-machine-types", args=[space.pk])
    response = authenticated_client(actor).get(url)
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.data}
    assert rows[printer.pk]["can_manage_public_queue"] is True
    assert not rows[local.pk].get("can_manage_public_queue", False)
    assert not rows[laser.pk].get("can_manage_public_queue", False)
    scoped = _manager(space, "queue-wrong-authority", machine_type=local)
    response = authenticated_client(scoped).get(url)
    assert response.status_code == 200
    assert not any(row.get("can_manage_public_queue", False) for row in response.data)
