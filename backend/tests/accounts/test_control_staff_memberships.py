"""/control/ can make staff: the membership inline sets a real role, mirrors it and audits it."""

from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.admin_membership_inline import (
    MakerspaceMembershipInline as UserMembershipInline,
    space_manager_label_warning,
)
from apps.accounts.models import User
from apps.accounts.services_social_login import assert_staff_authority
from apps.audit.models import AuditLog
from apps.makerspaces import limits
from apps.makerspaces.admin_staff_membership import (
    MakerspaceMembershipInline,
    StaffMembershipForm,
    audit_staff_memberships,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.roles import ensure_default_roles
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


def _space(slug):
    space = make_space(slug)
    ensure_default_roles(space)
    return space


def _form(user, space, role):
    return StaffMembershipForm(data={"user": user.pk, "makerspace": space.pk, "assigned_role": role.pk if role else ""})


def test_space_manager_label_alone_warns_and_a_membership_fixes_login():
    space = _space("ctl-sm")
    user = make_user("ctl-sm-user", role=User.Role.SPACE_MANAGER, access_status=User.AccessStatus.ACTIVE)
    assert "has no Space Manager membership" in space_manager_label_warning(user)

    form = _form(user, space, space.roles.get(legacy_role="space_manager"))
    assert form.is_valid(), form.errors
    membership = form.save()
    assert (membership.role, membership.status) == (MakerspaceMembership.Role.SPACE_MANAGER, "active")
    assert space_manager_label_warning(user) is None
    assert_staff_authority(user, RequestFactory().post("/api/v1/auth/login"))


def test_custom_role_mirrors_custom_and_role_is_required():
    space = _space("ctl-custom")
    user = make_user("ctl-custom-user")
    custom = space.roles.create(name="Front desk", slug="front-desk", granted_actions=["issue_request"])
    form = _form(user, space, custom)
    assert form.is_valid(), form.errors
    assert form.save().role == MakerspaceMembership.Role.CUSTOM
    # No role picked must not fall back to the model's Space Manager default.
    assert not _form(make_user("ctl-custom-blank"), space, None).is_valid()


def test_role_from_another_makerspace_or_hidden_space_is_refused():
    space, other = _space("ctl-own"), _space("ctl-other")
    user = make_user("ctl-cross-user")
    assert not _form(user, space, other.roles.get(legacy_role="space_manager")).is_valid()
    other.superadmin_access_enabled = False
    other.save(update_fields=["superadmin_access_enabled"])
    assert not _form(user, other, other.roles.get(legacy_role="space_manager")).is_valid()


def test_saving_a_role_reactivates_a_revoked_membership():
    space = _space("ctl-revoked")
    user = make_user("ctl-revoked-user")
    membership = MakerspaceMembership.objects.create(
        user=user, makerspace=space, role=MakerspaceMembership.Role.SPACE_MANAGER,
        status="revoked", revocation_reason="left",
    )
    form = StaffMembershipForm(
        data={"user": user.pk, "makerspace": space.pk, "assigned_role": space.roles.get(legacy_role="machine_manager").pk},
        instance=membership,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.status, saved.revocation_reason, saved.role) == ("active", "", "machine_manager")


def test_inline_writes_are_audited():
    space = _space("ctl-audit")
    actor = make_user("ctl-audit-admin", role=User.Role.SUPERADMIN, is_superuser=True)
    membership = MakerspaceMembership.objects.create(
        user=make_user("ctl-audit-user"), makerspace=space,
        assigned_role=space.roles.get(legacy_role="space_manager"),
    )
    formset = SimpleNamespace(model=MakerspaceMembership, new_objects=[membership], changed_objects=[], deleted_objects=[])
    audit_staff_memberships(SimpleNamespace(user=actor), formset)
    entry = AuditLog.objects.get(action="staff.created")
    assert entry.meta["via"] == "control"
    assert entry.meta["role_slug"] == "space_manager"


def _superadmin_request():
    request = RequestFactory().get("/control/")
    request.user = make_user("ctl-inline-admin", role=User.Role.SUPERADMIN, is_superuser=True, is_staff=True)
    return request


def _hide(space):
    space.superadmin_access_enabled = False
    space.save(update_fields=["superadmin_access_enabled"])


def test_makerspace_page_offers_its_roles_without_narrowing_other_pages():
    space, other = _space("ctl-narrow-a"), _space("ctl-narrow-b")
    inline = MakerspaceMembershipInline(Makerspace, admin.site)
    form = inline.get_formset(_superadmin_request(), space)(instance=space).empty_form
    # Every staff role of this space, and not the action-less Member role.
    assert set(form.fields["assigned_role"].queryset) == set(space.roles.exclude(slug="member"))
    # The User page and Makerspace memberships -> Add share the form class; opening one
    # makerspace's page used to narrow their role list for the whole process.
    assert set(other.roles.exclude(slug="member")) <= set(StaffMembershipForm().fields["assigned_role"].queryset)


def test_hidden_makerspaces_roles_and_rows_are_not_offered():
    visible, hidden = _space("ctl-vis"), _space("ctl-hid")
    user = make_user("ctl-hidden-rows")
    shown = MakerspaceMembership.objects.create(
        user=user, makerspace=visible, assigned_role=visible.roles.get(slug="member"),
    )
    kept = MakerspaceMembership.objects.create(
        user=user, makerspace=hidden, assigned_role=hidden.roles.get(legacy_role="space_manager"),
    )
    _hide(hidden)
    assert not set(hidden.roles.all()) & set(StaffMembershipForm().fields["assigned_role"].queryset)
    rows = UserMembershipInline(User, admin.site).get_queryset(_superadmin_request()).filter(user=user)
    # A listed hidden row would also fail every save of this user's page.
    assert list(rows) == [shown]
    assert MakerspaceMembership.objects.filter(pk=kept.pk).exists()


def test_an_existing_membership_cannot_be_moved_to_another_user_or_space():
    space, other = _space("ctl-move-a"), _space("ctl-move-b")
    user = make_user("ctl-move-user")
    role = space.roles.get(legacy_role="machine_manager")
    membership = MakerspaceMembership.objects.create(user=user, makerspace=space, assigned_role=role)
    form = StaffMembershipForm(
        data={"user": make_user("ctl-move-other").pk, "makerspace": other.pk, "assigned_role": role.pk},
        instance=membership,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.user_id, saved.makerspace_id) == (user.pk, space.pk)


def test_a_hidden_membership_cannot_be_moved_out_of_its_makerspace():
    hidden, visible = _space("ctl-escape-h"), _space("ctl-escape-v")
    membership = MakerspaceMembership.objects.create(
        user=make_user("ctl-escape-user"), makerspace=hidden,
        assigned_role=hidden.roles.get(legacy_role="space_manager"),
    )
    _hide(hidden)
    form = StaffMembershipForm(
        data={"user": membership.user_id, "makerspace": visible.pk,
              "assigned_role": visible.roles.get(legacy_role="space_manager").pk},
        instance=membership,
    )
    assert not form.is_valid()
    membership.refresh_from_db()
    assert membership.makerspace_id == hidden.pk


def test_granting_staff_checks_archive_and_the_staff_quota_like_add_staff(monkeypatch):
    archived = _space("ctl-archived")
    Makerspace.objects.filter(pk=archived.pk).update(archived_at=timezone.now())
    archived.refresh_from_db()
    form = _form(make_user("ctl-archived-user"), archived, archived.roles.get(legacy_role="machine_manager"))
    assert not form.is_valid()
    assert "archived" in str(form.errors)

    capped = _space("ctl-capped")
    capped.resource_limit_overrides = {"staff": 0}
    capped.save(update_fields=["resource_limit_overrides"])
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    form = _form(make_user("ctl-capped-user"), capped, capped.roles.get(legacy_role="space_manager"))
    assert not form.is_valid()
    assert "limit" in str(form.errors)


def test_a_legacy_row_without_a_role_does_not_block_saving():
    space = _space("ctl-legacy")
    membership = MakerspaceMembership.objects.create(
        user=make_user("ctl-legacy-user"), makerspace=space, role=MakerspaceMembership.Role.MACHINE_MANAGER,
        status="revoked",
    )
    MakerspaceMembership.objects.filter(pk=membership.pk).update(assigned_role=None)
    membership.refresh_from_db()
    form = StaffMembershipForm(
        data={"user": membership.user_id, "makerspace": space.pk, "assigned_role": ""}, instance=membership,
    )
    assert form.is_valid(), form.errors
    # Untouched, it is not a grant: the revoked row stays revoked.
    assert form.save().status == "revoked"


def test_member_role_is_not_a_staff_grant_but_stays_on_existing_members():
    space = _space("ctl-member-role")
    member_role = space.roles.get(slug="member")
    assert member_role not in StaffMembershipForm().fields["assigned_role"].queryset
    assert not _form(make_user("ctl-member-new"), space, member_role).is_valid()
    existing = MakerspaceMembership.objects.create(
        user=make_user("ctl-member-existing"), makerspace=space, assigned_role=member_role,
    )
    form = StaffMembershipForm(
        data={"user": existing.user_id, "makerspace": space.pk, "assigned_role": member_role.pk}, instance=existing,
    )
    assert form.is_valid(), form.errors
