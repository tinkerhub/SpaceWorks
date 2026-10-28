"""Personal machine-type links: one member's reach on top of their role's links.

A personal link only widens a MANAGE_MACHINES grant the member's role already holds. It
must never grant the action, never leak to another member of the same role, and never
reach a type that neither the role nor the member is linked to.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.audit.models import AuditLog
from apps.machines import access, role_scope
from apps.machines.models import (
    Machine,
    MachineType,
    MembershipMachineTypeScope,
    RoleMachineTypeScope,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole

pytestmark = pytest.mark.django_db


def _user(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )


@pytest.fixture
def lab():
    space = Makerspace.objects.create(name="member-scope", slug="member-scope")
    printers = MachineType.objects.create(slug="ms-printer", name="Printer", makerspace=space)
    lasers = MachineType.objects.create(slug="ms-laser", name="Laser", makerspace=space)
    printer = Machine.objects.create(makerspace=space, machine_type=printers, name="Prusa")
    laser = Machine.objects.create(makerspace=space, machine_type=lasers, name="Glowforge")
    boss = _user("ms-boss")
    MakerspaceMembership.objects.create(
        user=boss, makerspace=space, role=MakerspaceMembership.Role.SPACE_MANAGER
    )
    # A Machines role with NO type links: on its own it reaches nothing.
    staff_role = MakerspaceRole.objects.create(
        makerspace=space, name="Machine staff", slug="machine-staff",
        granted_actions=[Action.MANAGE_MACHINES],
    )
    viewer_role = MakerspaceRole.objects.create(
        makerspace=space, name="Viewer", slug="viewer", granted_actions=[Action.VIEW_INVENTORY],
    )
    ahmed, riya = _user("ms-ahmed"), _user("ms-riya")
    ahmed_m = MakerspaceMembership.objects.create(
        user=ahmed, makerspace=space, role=MakerspaceMembership.Role.CUSTOM, assigned_role=staff_role
    )
    riya_m = MakerspaceMembership.objects.create(
        user=riya, makerspace=space, role=MakerspaceMembership.Role.CUSTOM, assigned_role=staff_role
    )
    return {
        "space": space, "printers": printers, "lasers": lasers, "printer": printer, "laser": laser,
        "boss": boss, "staff_role": staff_role, "viewer_role": viewer_role,
        "ahmed": ahmed, "ahmed_m": ahmed_m, "riya": riya, "riya_m": riya_m,
    }


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def scope_url(lab, membership=None):
    return reverse(
        "admin-membership-machine-scope",
        args=[lab["space"].id, (membership or lab["ahmed_m"]).pk],
    )


# --- resolution ---------------------------------------------------------------------


def test_personal_type_reaches_only_that_type(lab):
    MembershipMachineTypeScope.objects.create(membership=lab["ahmed_m"], machine_type=lab["lasers"])

    assert access.can_manage_machine(lab["ahmed"], lab["laser"]) is True
    assert access.can_manage_machine(lab["ahmed"], lab["printer"]) is False
    assert access.can_see_machines(lab["ahmed"], lab["space"].id) is True


def test_personal_links_do_not_leak_to_another_member_of_the_same_role(lab):
    MembershipMachineTypeScope.objects.create(membership=lab["ahmed_m"], machine_type=lab["lasers"])

    assert access.can_manage_machine(lab["riya"], lab["laser"]) is False
    assert access.can_see_machines(lab["riya"], lab["space"].id) is False


def test_personal_and_role_links_are_a_union(lab):
    RoleMachineTypeScope.objects.create(role=lab["staff_role"], machine_type=lab["printers"])
    MembershipMachineTypeScope.objects.create(membership=lab["ahmed_m"], machine_type=lab["lasers"])

    scope = role_scope.manage_scope_for(lab["ahmed"], lab["space"].id)
    assert scope[0] == frozenset({lab["printers"].pk, lab["lasers"].pk})
    # Riya shares the role, so she gets its printer link and nothing personal.
    assert role_scope.manage_scope_for(lab["riya"], lab["space"].id)[0] == frozenset({lab["printers"].pk})


def test_a_personal_link_never_grants_the_machines_action(lab):
    lab["ahmed_m"].assigned_role = lab["viewer_role"]
    lab["ahmed_m"].save(update_fields=["assigned_role"])
    MembershipMachineTypeScope.objects.create(membership=lab["ahmed_m"], machine_type=lab["lasers"])

    assert access.can_manage_machine(lab["ahmed"], lab["laser"]) is False
    assert access.can_see_machines(lab["ahmed"], lab["space"].id) is False


def test_membership_keyed_resolution_matches_the_actor_path(lab):
    MembershipMachineTypeScope.objects.create(membership=lab["ahmed_m"], machine_type=lab["lasers"])

    resolved = role_scope.manage_scopes_for_memberships(
        MakerspaceMembership.objects.select_related("assigned_role").filter(
            pk__in=[lab["ahmed_m"].pk, lab["riya_m"].pk]
        )
    )
    assert resolved[lab["ahmed_m"].pk] == role_scope.manage_scope_for(lab["ahmed"], lab["space"].id)
    assert resolved[lab["riya_m"].pk] == (frozenset(), frozenset())


# --- API ----------------------------------------------------------------------------


def test_the_editor_reports_personal_role_and_available_types(lab):
    RoleMachineTypeScope.objects.create(role=lab["staff_role"], machine_type=lab["printers"])
    MembershipMachineTypeScope.objects.create(membership=lab["ahmed_m"], machine_type=lab["lasers"])

    body = client_for(lab["boss"]).get(scope_url(lab)).json()

    assert body["machine_type_ids"] == [lab["lasers"].pk]
    assert body["role_machine_type_ids"] == [lab["printers"].pk]
    assert {lab["printers"].pk, lab["lasers"].pk} <= {row["id"] for row in body["available_machine_types"]}
    assert body["scoping_applies"] is True
    assert body["role_covers_all"] is False


def test_a_space_manager_member_is_reported_as_covering_everything(lab):
    boss_m = MakerspaceMembership.objects.get(user=lab["boss"], makerspace=lab["space"])

    body = client_for(lab["boss"]).get(scope_url(lab, boss_m)).json()

    assert body["scoping_applies"] is False
    assert body["role_covers_all"] is True


def test_saving_replaces_the_selection_and_is_audited(lab):
    MembershipMachineTypeScope.objects.create(membership=lab["ahmed_m"], machine_type=lab["printers"])

    response = client_for(lab["boss"]).put(
        scope_url(lab), {"machine_type_ids": [lab["lasers"].pk]}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["machine_type_ids"] == [lab["lasers"].pk]
    assert list(
        MembershipMachineTypeScope.objects.filter(membership=lab["ahmed_m"]).values_list("machine_type_id", flat=True)
    ) == [lab["lasers"].pk]
    entry = AuditLog.objects.get(action="membership.machine_scope_changed")
    assert entry.meta["before"] == [lab["printers"].pk]
    assert entry.meta["after"] == [lab["lasers"].pk]


def test_another_makerspaces_type_is_rejected_not_dropped(lab):
    other = Makerspace.objects.create(name="other-ms", slug="other-ms")
    foreign = MachineType.objects.create(slug="ms-foreign", name="Foreign", makerspace=other)

    response = client_for(lab["boss"]).put(
        scope_url(lab), {"machine_type_ids": [foreign.pk]}, format="json"
    )

    assert response.status_code == 400
    assert not MembershipMachineTypeScope.objects.exists()


def test_only_a_space_manager_may_edit(lab):
    response = client_for(lab["ahmed"]).put(
        scope_url(lab, lab["riya_m"]), {"machine_type_ids": [lab["lasers"].pk]}, format="json"
    )

    assert response.status_code in {403, 404}
    assert not MembershipMachineTypeScope.objects.exists()


def test_a_membership_of_another_makerspace_is_not_found(lab):
    other = Makerspace.objects.create(name="other-ms2", slug="other-ms2")
    stranger = MakerspaceMembership.objects.create(
        user=_user("ms-stranger"), makerspace=other, role=MakerspaceMembership.Role.CUSTOM
    )

    response = client_for(lab["boss"]).get(scope_url(lab, stranger))

    assert response.status_code == 404
