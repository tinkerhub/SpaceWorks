from django.contrib import messages

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.admin_staff_membership import (
    StaffMembershipInline,
    audit_staff_memberships,
)
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.servability import servable_queryset


class MakerspaceMembershipInline(StaffMembershipInline):
    """Make someone staff from their User page: pick the makerspace and its role."""

    fk_name = "user"
    fields = ("makerspace", "assigned_role")
    autocomplete_fields = ("makerspace",)


class StaffMembershipAdminMixin:
    """UserAdmin hooks: audit inline membership writes and flag a label-only manager."""

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        audit_staff_memberships(request, formset)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        warning = space_manager_label_warning(form.instance)
        if warning:
            self.message_user(request, warning, level=messages.WARNING)


def space_manager_label_warning(user):
    """Explain a Space Manager label that grants no sign-in.

    `User.role` is a label; staff sign-in is decided by memberships alone, so a superadmin
    who sets it in /control/ otherwise hands out a login that fails with no hint why.
    """
    if user.role != User.Role.SPACE_MANAGER:
        return None
    memberships = servable_queryset(
        MakerspaceMembership.objects.filter(user=user, status="active"),
        relation="makerspace",
    ).select_related("assigned_role")
    if any(
        rbac.Action.MANAGE_MAKERSPACE in rbac.actions_for_membership(row)
        for row in memberships
    ):
        return None
    return (
        f"Role is a label only: {user.username} has no Space Manager membership, so they "
        "cannot sign in to a makerspace staff console. Add a row under Makerspace "
        "memberships below with the makerspace and its Space Manager role."
    )
