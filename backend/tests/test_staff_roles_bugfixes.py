"""Staff/role/module/container/report bug fixes: external behaviour of each fix."""
import pytest
from django.urls import reverse

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import Box
from apps.makerspaces.models import (
    MakerspaceMembership,
    MakerspaceRole,
    MembershipRequest,
)
from tests.return_helpers import (
    authenticated_client,
    make_box,
    make_member,
    make_space,
    make_user,
)

pytestmark = pytest.mark.django_db


def _seeded(makerspace, legacy_role):
    return MakerspaceRole.objects.get(makerspace=makerspace, legacy_role=legacy_role)


def _superadmin(username):
    return make_user(username, role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)


def _custom_member(username, makerspace, actions):
    user = make_user(username, access_status=User.AccessStatus.ACTIVE)
    role = MakerspaceRole.objects.create(
        makerspace=makerspace, name=f"{username} role", slug=f"{username}-role",
        granted_actions=sorted(actions),
    )
    MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace, role=MakerspaceMembership.Role.CUSTOM, assigned_role=role,
    )
    return user


# --- 1. "Remove role" revokes instead of hard-deleting -------------------------------


def test_remove_role_revokes_membership_and_records_the_removed_role():
    makerspace = make_space("fix-revoke")
    manager = make_member("fix-revoke-sm", makerspace)
    target = make_user("fix-revoke-target", access_status=User.AccessStatus.ACTIVE)
    role = _seeded(makerspace, MakerspaceMembership.Role.MACHINE_MANAGER)
    membership = MakerspaceMembership.objects.create(
        user=target, makerspace=makerspace,
        role=MakerspaceMembership.Role.MACHINE_MANAGER, assigned_role=role,
    )
    pending = MembershipRequest.objects.create(
        makerspace=makerspace, user=target, kind=MembershipRequest.Kind.REQUEST,
        state=MembershipRequest.State.REQUESTED,
    )

    response = authenticated_client(manager).delete(f"/api/v1/admin/memberships/{membership.id}")

    assert response.status_code == 204
    membership.refresh_from_db()
    assert membership.status == "revoked"
    assert membership.revoked_by_id == manager.id
    pending.refresh_from_db()
    assert pending.state == MembershipRequest.State.REVOKED
    log = AuditLog.objects.get(action="staff.membership_revoked", target_id=str(target.id))
    assert log.meta["assigned_role_id"] == role.id
    assert log.meta["assigned_role_name"] == role.name
    assert AuditLog.objects.filter(action="membership.revoked", makerspace=makerspace).exists()
    # Revoked means no authority any more.
    assert not rbac.can(target, rbac.Action.MANAGE_MACHINES, makerspace.id)


def test_remove_role_keeps_the_scope_contract():
    makerspace, other = make_space("fix-revoke-scope"), make_space("fix-revoke-scope-other")
    manager = make_member("fix-revoke-scope-sm", makerspace)
    peer = make_member("fix-revoke-scope-peer", makerspace)
    outsider = make_member(
        "fix-revoke-scope-out", other,
        membership_role=MakerspaceMembership.Role.MACHINE_MANAGER, role=User.Role.REQUESTER,
    )
    api = authenticated_client(manager)
    peer_membership = MakerspaceMembership.objects.get(user=peer)
    outsider_membership = MakerspaceMembership.objects.get(user=outsider)

    assert api.delete(f"/api/v1/admin/memberships/{peer_membership.id}").status_code == 403
    assert api.delete(f"/api/v1/admin/memberships/{outsider_membership.id}").status_code == 404
    peer_membership.refresh_from_db()
    outsider_membership.refresh_from_db()
    assert (peer_membership.status, outsider_membership.status) == ("active", "active")


# --- 2. A local manager cannot reshape a shared manager-level role -------------------


def test_space_manager_cannot_demote_a_shared_manage_makerspace_role():
    makerspace = make_space("fix-demote")
    manager = make_member("fix-demote-sm", makerspace)
    shared = MakerspaceRole.objects.create(
        makerspace=makerspace, name="Co-managers", slug="co-managers",
        granted_actions=sorted([rbac.Action.MANAGE_MAKERSPACE, rbac.Action.VIEW_INVENTORY]),
    )
    url = reverse("admin-role-detail", kwargs={"makerspace_id": makerspace.id, "role_id": shared.id})

    stripped = authenticated_client(manager).patch(
        url, {"granted_actions": [rbac.Action.VIEW_INVENTORY]}, format="json"
    )
    assert stripped.status_code == 403
    shared.refresh_from_db()
    assert rbac.Action.MANAGE_MAKERSPACE in shared.granted_actions
    # A rename stays a manager's call, and a superadmin may still change the grants.
    assert authenticated_client(manager).patch(url, {"name": "Leads"}, format="json").status_code == 200
    superadmin = authenticated_client(_superadmin("fix-demote-root"))
    assert superadmin.patch(url, {"granted_actions": [rbac.Action.VIEW_INVENTORY]}, format="json").status_code == 200


# --- 3. Email already in use is a 400, and the previous role is audited -------------


@pytest.mark.parametrize("route", ["legacy", "roles"])
def test_adding_staff_with_an_email_in_use_is_a_field_error(route):
    makerspace = make_space(f"fix-email-{route}")
    manager = make_member(f"fix-email-{route}-sm", makerspace)
    existing = make_user(f"fix-email-{route}-owner")
    payload = {"username": f"fix-email-{route}-new", "email": existing.email.upper()}
    if route == "legacy":
        url = reverse("admin-users-inventory-managers")
        payload |= {"makerspace_id": makerspace.id, "role": MakerspaceMembership.Role.INVENTORY_MANAGER}
    else:
        url = reverse("admin-membership-list-create", kwargs={"makerspace_id": makerspace.id})
        payload["role_id"] = _seeded(makerspace, MakerspaceMembership.Role.INVENTORY_MANAGER).id

    response = authenticated_client(manager).post(url, payload, format="json")

    assert response.status_code == 400
    assert "email" in response.data
    assert not User.objects.filter(username=payload["username"]).exists()


def test_changing_an_existing_staff_role_audits_the_previous_role():
    makerspace = make_space("fix-prev-role")
    manager = make_member("fix-prev-role-sm", makerspace)
    target = make_user("fix-prev-role-target", access_status=User.AccessStatus.ACTIVE)
    previous = _seeded(makerspace, MakerspaceMembership.Role.MACHINE_MANAGER)
    MakerspaceMembership.objects.create(
        user=target, makerspace=makerspace,
        role=MakerspaceMembership.Role.MACHINE_MANAGER, assigned_role=previous,
    )

    response = authenticated_client(manager).post(
        reverse("admin-users-inventory-managers"),
        {"username": target.username, "makerspace_id": makerspace.id,
         "role": MakerspaceMembership.Role.INVENTORY_MANAGER},
        format="json",
    )

    assert response.status_code == 201
    log = AuditLog.objects.get(action="staff.membership_updated", target_id=str(target.id))
    assert log.meta["previous_role_id"] == previous.id


# --- 4. Module console honours the superadmin hard-hide -----------------------------


def test_module_console_is_404_on_a_space_that_blocked_superadmin_access():
    makerspace = make_space("fix-modules-hidden")
    makerspace.superadmin_access_enabled = False
    makerspace.save(update_fields=["superadmin_access_enabled"])
    superadmin = _superadmin("fix-modules-root")
    # Even an explicit membership there does not carry the global module power.
    MakerspaceMembership.objects.create(
        user=superadmin, makerspace=makerspace, role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    api = authenticated_client(superadmin)

    assert api.get(reverse("admin-module-groups", args=[makerspace.id])).status_code == 404
    install = api.post(reverse("admin-module-install", args=[makerspace.id]), {"key": "events"}, format="json")
    assert install.status_code == 404


# --- 5. Duplicate container label is a typed 400 ------------------------------------


def test_duplicate_container_label_is_a_400_on_create_and_update():
    makerspace = make_space("fix-box-label")
    manager = make_member("fix-box-label-sm", makerspace)
    api = authenticated_client(manager)
    url = f"/api/v1/admin/makerspace/{makerspace.id}/containers"
    assert api.post(url, {"label": "Bin A"}, format="json").status_code == 201

    duplicate = api.post(url, {"label": "Bin A"}, format="json")

    assert duplicate.status_code == 400
    assert "label" in duplicate.data
    assert Box.objects.filter(makerspace=makerspace, label="Bin A").count() == 1
    other = make_box(makerspace, label="Bin B")
    renamed = api.patch(f"/api/v1/admin/containers/{other.id}", {"label": "Bin A"}, format="json")
    assert renamed.status_code == 400


# --- 6. Reports resolve by the report's own action ----------------------------------


def test_audit_only_role_can_preview_and_export_the_reports_it_is_listed():
    makerspace = make_space("fix-report-audit")
    auditor = _custom_member("fix-report-auditor", makerspace, {rbac.Action.VIEW_AUDIT})
    api = authenticated_client(auditor)

    catalog = api.get(reverse("report-catalog", args=[makerspace.id]))
    assert catalog.status_code == 200
    assert "taken-items" in {entry["key"] for entry in catalog.data["results"]}
    assert api.get(reverse("analytics-taken-items", args=[makerspace.id])).status_code == 200
    export = api.get(reverse("report-export", args=[makerspace.id, "taken-items"]))
    assert export.status_code == 200
    assert api.get(reverse("accountability-dashboard", args=[makerspace.id])).status_code == 200
    # A report it does not hold the action for stays out of reach.
    payments = api.get(reverse("report-export", args=[makerspace.id, "payment-reconciliation"]))
    assert payments.status_code == 404
