"""Printing's legacy type hook must not bypass role and personal machine scope."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.machines.models import (
    Machine, MachineServiceRequest, MachineType, MembershipMachineTypeScope,
    RoleMachineTypeScope, ServiceBucket,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole

pytestmark = pytest.mark.django_db


def client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def ids(response):
    assert response.status_code == 200
    body = response.json()
    return {row["id"] for row in (body["results"] if isinstance(body, dict) else body)}


@pytest.fixture
def lab():
    space = Makerspace.objects.create(name="Unified printing", slug="unified-printing")
    printers, _ = MachineType.objects.update_or_create(
        makerspace=None, slug="3d_printer",
        defaults={"name": "3D Printer", "is_builtin": True, "managing_action": "manage_printing"},
    )
    lasers = MachineType.objects.create(makerspace=space, slug="unified-laser", name="Laser")
    printer = Machine.objects.create(makerspace=space, machine_type=printers, name="Prusa")
    laser = Machine.objects.create(makerspace=space, machine_type=lasers, name="Laser")
    role = MakerspaceRole.objects.create(
        makerspace=space, name="Inventory and machines", slug="inventory-machines",
        granted_actions=["view_inventory", "edit_inventory", "manage_machines"],
    )
    users, memberships, jobs = [], [], []
    for name in ("one-printer-staffer", "inventory-coworker"):
        user = User.objects.create_user(username=name, access_status="active")
        users.append(user)
        memberships.append(MakerspaceMembership.objects.create(
            user=user, makerspace=space, role="custom", assigned_role=role,
        ))
    for machine in (printer, laser):
        bucket = ServiceBucket.objects.create(machine=machine, name="Jobs")
        jobs.append(MachineServiceRequest.objects.create(
            makerspace=space, requester=users[0], bucket=bucket, assigned_machine=machine,
            title=f"Job for {machine.name}", status=MachineServiceRequest.Status.COMPLETED,
        ))
    return space, printers, lasers, printer, laser, role, users, memberships, jobs


def test_personal_printer_selection_does_not_change_the_shared_inventory_role(lab):
    space, printers, _, printer, laser, role, users, memberships, jobs = lab
    MembershipMachineTypeScope.objects.create(membership=memberships[0], machine_type=printers)
    first, coworker = map(client, users)
    machine_list = reverse("admin-machines", args=[space.pk])
    queue = reverse("admin-machine-service-request-list-create", args=[space.pk])

    assert ids(first.get(machine_list)) == {printer.pk}
    assert ids(first.get(queue)) == {jobs[0].pk}
    assert first.get(reverse("admin-machine-detail", args=[printer.pk])).status_code == 200
    assert first.get(reverse("admin-machine-service-request-detail", args=[jobs[0].pk])).status_code == 200
    assert first.get(reverse("admin-machine-detail", args=[laser.pk])).status_code == 404
    assert coworker.get(machine_list).status_code == 403
    assert ids(coworker.get(queue)) == set()
    assert coworker.get(reverse("admin-machine-detail", args=[printer.pk])).status_code == 404
    assert coworker.get(reverse("admin-machine-service-request-detail", args=[jobs[0].pk])).status_code == 404
    for api in (first, coworker):
        assert api.get(reverse("admin-inventory", args=[space.pk])).status_code == 200
    role.refresh_from_db()
    assert set(role.granted_actions) == {"view_inventory", "edit_inventory", "manage_machines"}
    assert not RoleMachineTypeScope.objects.filter(role=role).exists()


@pytest.mark.parametrize("selection", ["printer", "laser", "empty"])
def test_scoped_machine_only_roles_do_not_get_an_implied_printing_bypass(lab, selection):
    space, printers, lasers, printer, laser, role, users, _, jobs = lab
    role.granted_actions = ["manage_machines"]
    role.save(update_fields=["granted_actions"])
    selected_type = {"printer": printers, "laser": lasers}.get(selection)
    if selected_type is not None:
        RoleMachineTypeScope.objects.create(role=role, machine_type=selected_type)
    api = client(users[0])
    machine_list = reverse("admin-machines", args=[space.pk])
    queue = reverse("admin-machine-service-request-list-create", args=[space.pk])
    selected_machine = {"printer": printer, "laser": laser}.get(selection)
    expected_machines = {selected_machine.pk} if selected_machine else set()
    expected_jobs = {jobs[0].pk} if selection == "printer" else {jobs[1].pk} if selection == "laser" else set()
    if selected_machine:
        assert ids(api.get(machine_list)) == expected_machines
    else:
        assert api.get(machine_list).status_code == 403
    assert ids(api.get(queue)) == expected_jobs
    for job in jobs:
        response = api.get(reverse("admin-machine-service-request-detail", args=[job.pk]))
        assert response.status_code == (200 if job.pk in expected_jobs else 404)

    forbidden = laser if selection == "printer" else printer
    before_audit = AuditLog.objects.count()
    original_name = forbidden.name
    response = api.patch(reverse("admin-machine-detail", args=[forbidden.pk]), {
        "name": "Unauthorized rename",
    }, format="json")
    assert response.status_code == 404
    forbidden.refresh_from_db()
    assert forbidden.name == original_name
    assert AuditLog.objects.count() == before_audit
