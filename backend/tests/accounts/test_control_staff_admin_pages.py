"""The /control/ staff pages end to end: real admin requests, not the form in isolation."""

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.roles import ensure_default_roles
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


def _client():
    client = Client()
    client.force_login(make_user(
        "ctl-pages-admin", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
        is_staff=True, is_superuser=True,
    ))
    return client


def _space(slug, *, hidden=False):
    space = make_space(slug)
    ensure_default_roles(space)
    if hidden:
        space.superadmin_access_enabled = False
        space.save(update_fields=["superadmin_access_enabled"])
    return space


def test_adding_a_membership_grants_mirrors_and_audits():
    client, space = _client(), _space("ctl-pages-add")
    user = make_user("ctl-pages-new-staff", access_status=User.AccessStatus.ACTIVE)
    role = space.roles.get(legacy_role="space_manager")
    assert client.get(reverse("admin:makerspaces_makerspacemembership_add")).status_code == 200
    response = client.post(
        reverse("admin:makerspaces_makerspacemembership_add"),
        {"user": user.pk, "makerspace": space.pk, "assigned_role": role.pk},
    )
    assert response.status_code == 302, response.context["adminform"].form.errors if response.context else response
    membership = MakerspaceMembership.objects.get(user=user, makerspace=space)
    assert (membership.assigned_role_id, membership.role, membership.status) == (role.pk, "space_manager", "active")
    entry = AuditLog.objects.get(action="staff.created", target_id=str(user.pk))
    assert entry.meta["via"] == "control"


def test_an_existing_membership_page_renders_and_cannot_retarget():
    client, space, other = _client(), _space("ctl-pages-edit"), _space("ctl-pages-edit-other")
    user = make_user("ctl-pages-edit-user")
    membership = MakerspaceMembership.objects.create(
        user=user, makerspace=space, assigned_role=space.roles.get(legacy_role="machine_manager"),
    )
    url = reverse("admin:makerspaces_makerspacemembership_change", args=[membership.pk])
    assert client.get(url).status_code == 200
    role = space.roles.get(legacy_role="inventory_manager")
    response = client.post(url, {"user": make_user("ctl-pages-intruder").pk, "makerspace": other.pk, "assigned_role": role.pk})
    assert response.status_code == 302
    membership.refresh_from_db()
    assert (membership.user_id, membership.makerspace_id, membership.assigned_role_id) == (user.pk, space.pk, role.pk)
    assert AuditLog.objects.filter(action="staff.membership_updated", target_id=str(user.pk)).count() == 1
    # Saving again with nothing changed writes no audit entry.
    client.post(url, {"assigned_role": role.pk})
    assert AuditLog.objects.filter(action="staff.membership_updated", target_id=str(user.pk)).count() == 1


def test_revoke_action_runs_the_revocation_service():
    client, space = _client(), _space("ctl-pages-revoke")
    membership = MakerspaceMembership.objects.create(
        user=make_user("ctl-pages-revoke-user"), makerspace=space,
        assigned_role=space.roles.get(legacy_role="machine_manager"),
    )
    response = client.post(
        reverse("admin:makerspaces_makerspacemembership_changelist"),
        {"action": "revoke_memberships", ACTION_CHECKBOX_NAME: [str(membership.pk)], "index": "0"},
        follow=True,
    )
    assert response.status_code == 200
    membership.refresh_from_db()
    assert membership.status == "revoked"
    assert AuditLog.objects.filter(action="membership.revoked", makerspace=space).exists()
    # Deleting is not offered: revocation is the only way out.
    actions = [name for name, _label in response.context["action_form"].fields["action"].choices]
    assert "revoke_memberships" in actions and "delete_selected" not in actions


def test_pages_render_without_hidden_spaces_or_a_new_space_inline():
    client = _client()
    visible, hidden = _space("ctl-pages-visible"), _space("ctl-pages-secret", hidden=True)
    user = make_user("ctl-pages-both")
    for space in (visible, hidden):
        MakerspaceMembership.objects.create(
            user=user, makerspace=space, assigned_role=space.roles.get(legacy_role="machine_manager"),
        )
    user_page = client.get(reverse("admin:accounts_user_change", args=[user.pk]))
    assert user_page.status_code == 200
    assert "ctl-pages-visible" in user_page.content.decode()
    assert "ctl-pages-secret" not in user_page.content.decode()
    space_page = client.get(reverse("admin:makerspaces_makerspace_change", args=[visible.pk]))
    assert space_page.status_code == 200
    assert space_page.context["inline_admin_formsets"]
    add_page = client.get(reverse("admin:makerspaces_makerspace_add"))
    assert add_page.status_code == 200
    assert not add_page.context["inline_admin_formsets"]
