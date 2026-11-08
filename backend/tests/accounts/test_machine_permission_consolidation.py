"""Local grant writes use one machine action; compatibility aliases stay read-only."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.machines import access
from apps.machines.models import Machine, MachineType, MembershipMachineTypeScope
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole

pytestmark = pytest.mark.django_db


def client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


@pytest.fixture
def lab():
    space = Makerspace.objects.create(name="Unified roles", slug="unified-roles")
    boss = User.objects.create_user(username="unified-boss", access_status="active")
    MakerspaceMembership.objects.create(user=boss, makerspace=space, role="space_manager")
    role = MakerspaceRole.objects.create(
        makerspace=space, name="Inventory and machines", slug="inventory-machines",
        granted_actions=["view_inventory", "edit_inventory", "manage_machines"],
    )
    return space, boss, role


def role_url(space, role=None):
    if role is None:
        return reverse("admin-role-list-create", args=[space.pk])
    return reverse("admin-role-detail", args=[space.pk, role.pk])


@pytest.mark.parametrize("modules_on", [True, False])
@pytest.mark.parametrize("editing", [True, False])
def test_catalog_has_no_editable_printing_alias_even_for_held_dormant_grants(lab, modules_on, editing):
    space, boss, role = lab
    # A raw historical grant is still readable but cannot reappear in the picker.
    role.granted_actions.append("manage_printing")
    role.save(update_fields=["granted_actions"])
    if not modules_on:
        space.enabled_modules = []
        space.save(update_fields=["enabled_modules"])
    response = client(boss).get(
        reverse("admin-role-capabilities", args=[space.pk]),
        {"role_id": role.pk} if editing else {},
    )
    assert response.status_code == 200
    values = [row["value"] for row in response.data]
    assert "manage_printing" not in values
    assert values.count("manage_machines") == int(modules_on or editing)
    if modules_on or editing:
        machine = next(row for row in response.data if row["value"] == "manage_machines")
        assert "printing" in machine["description"].lower()
        assert "selected" in machine["description"].lower()


@pytest.mark.parametrize("superadmin", [False, True])
@pytest.mark.parametrize("creating", [False, True])
def test_alias_is_a_field_error_and_rejection_has_no_partial_writes(lab, superadmin, creating):
    space, boss, role = lab
    actor = User.objects.create_user(
        username="unified-root", role="superadmin", is_superuser=True, access_status="active",
    ) if superadmin else boss
    before_role = MakerspaceRole.objects.values().get(pk=role.pk)
    before_roles = MakerspaceRole.objects.count()
    before_audit = list(AuditLog.objects.order_by("pk").values())
    api = client(actor)
    payload = {"name": "Must not persist", "granted_actions": ["view_inventory", "manage_printing"]}
    response = (api.post if creating else api.patch)(
        role_url(space, None if creating else role), payload, format="json",
    )
    assert response.status_code == 400
    assert "granted_actions" in response.data
    assert "manage_machines" in str(response.data["granted_actions"])
    assert MakerspaceRole.objects.values().get(pk=role.pk) == before_role
    assert MakerspaceRole.objects.count() == before_roles
    assert list(AuditLog.objects.order_by("pk").values()) == before_audit


def test_creating_a_machine_role_starts_without_machine_reach(lab):
    space, boss, _ = lab
    response = client(boss).post(role_url(space), {
        "name": "New machine staff", "granted_actions": ["view_inventory", "manage_machines"],
    }, format="json")
    assert response.status_code == 201
    role = MakerspaceRole.objects.get(pk=response.data["id"])
    worker = User.objects.create_user(username="empty-scope-worker", access_status="active")
    MakerspaceMembership.objects.create(user=worker, makerspace=space, role="custom", assigned_role=role)
    machine_type = MachineType.objects.create(makerspace=space, slug="empty-printer", name="Printer")
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Printer")
    scope = client(boss).get(reverse("admin-role-machine-scope", args=[space.pk, role.pk]))
    assert scope.status_code == 200
    assert scope.data["scoping_applies"] is True
    assert scope.data["machine_type_ids"] == scope.data["machine_ids"] == []
    assert access.can_manage_machine(worker, machine) is False
    assert client(worker).get(reverse("admin-machines", args=[space.pk])).status_code == 403
    assert AuditLog.objects.filter(action="role.created", makerspace=space).exists()


def test_removing_machine_capability_makes_retained_personal_links_inert(lab):
    space, boss, role = lab
    worker = User.objects.create_user(username="revoked-printer-worker", access_status="active")
    membership = MakerspaceMembership.objects.create(
        user=worker, makerspace=space, role="custom", assigned_role=role,
    )
    printers, _ = MachineType.objects.update_or_create(
        makerspace=None, slug="3d_printer",
        defaults={"name": "3D Printer", "is_builtin": True, "managing_action": "manage_printing"},
    )
    machine = Machine.objects.create(makerspace=space, machine_type=printers, name="Personal printer")
    link = MembershipMachineTypeScope.objects.create(membership=membership, machine_type=printers)
    detail_url = reverse("admin-machine-detail", args=[machine.pk])
    assert client(worker).get(detail_url).status_code == 200

    response = client(boss).patch(role_url(space, role), {
        "granted_actions": ["view_inventory", "edit_inventory"],
    }, format="json")

    assert response.status_code == 200
    assert MembershipMachineTypeScope.objects.filter(pk=link.pk).exists()
    assert access.can_manage_machine(worker, machine) is False
    assert client(worker).get(detail_url).status_code == 404
    assert client(worker).get(reverse("admin-inventory", args=[space.pk])).status_code == 200
    scope = client(boss).get(reverse("admin-membership-machine-scope", args=[space.pk, membership.pk]))
    assert scope.data["scoping_applies"] is False
    assert AuditLog.objects.filter(action="role.updated", makerspace=space).exists()
