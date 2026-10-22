"""Membership invitations with the `membership` module off (D3).

Invitations run staff and community intent down one path, discriminated by the role's
granted actions. Community invitations are re-checked under the makerspace lock at
claim and activation (a module switched off after the invitation went out must still
stop it); staff invitations are core RBAC and keep working end to end.
"""

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces import membership_services
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MembershipRequest,
)
from apps.makerspaces.module_install import install_module
from tests.module_helpers import disable_module


pytestmark = pytest.mark.django_db


def _user(name):
    user = User.objects.create_user(
        username=name, email=f"{name}@example.test", access_status=User.AccessStatus.ACTIVE
    )
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    return user


def _space(slug):
    space = Makerspace.objects.create(name=slug, slug=slug)
    install_module(space, "membership")
    space.refresh_from_db()
    return space


def _role(space, slug):
    return MakerspaceRole.objects.get(makerspace=space, slug=slug)


def _manager(space, name):
    actor = _user(name)
    MakerspaceMembership.objects.create(
        makerspace=space, user=actor, assigned_role=_role(space, "space_manager"),
        role=MakerspaceMembership.Role.SPACE_MANAGER, status="active",
    )
    return actor


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_community_invitation_claim_is_refused_after_the_module_is_switched_off():
    space = _space("d3-claim-community")
    invitee = _user("d3-claim-community-invitee")
    invitation = membership_services.invite_membership(
        _manager(space, "d3-claim-community-manager"), space, invitee.email, _role(space, "member")
    )
    disable_module(space, "membership")

    with pytest.raises(ValidationError) as exc:
        membership_services.claim_invitation(invitee, invitation.pk)

    invitation.refresh_from_db()
    assert "module" in exc.value.detail
    assert invitation.state == MembershipRequest.State.INVITED
    assert not AuditLog.objects.filter(action="membership.invitation_claimed").exists()


def test_referral_activation_is_refused_after_the_module_is_switched_off():
    space = _space("d3-claim-referral")
    space.referrals_enabled = True
    space.save(update_fields=["referrals_enabled"])
    referrer = _user("d3-claim-referrer")
    MakerspaceMembership.objects.create(
        makerspace=space, user=referrer, assigned_role=_role(space, "member"),
        role=MakerspaceMembership.Role.CUSTOM, status="active", can_refer=True,
    )
    invitee = _user("d3-claim-referred")
    invitation = membership_services.refer_membership(referrer, space, invitee.email)
    disable_module(space, "membership")

    with pytest.raises(ValidationError):
        membership_services.claim_invitation(invitee, invitation.pk)

    assert not MakerspaceMembership.objects.filter(makerspace=space, user=invitee).exists()


def test_community_requests_are_hidden_and_unrevocable_with_the_module_off():
    space = _space("d3-queue-community")
    manager = _manager(space, "d3-queue-community-manager")
    joiner = _user("d3-queue-joiner")
    space.membership_policy = Makerspace.MembershipPolicy.REQUEST
    space.save(update_fields=["membership_policy"])
    request = membership_services.request_membership(joiner, space)
    disable_module(space, "membership")
    client = _client(manager)

    listed = client.get("/api/v1/admin/membership-requests", {"makerspace_id": space.pk})
    revoked = client.post(f"/api/v1/admin/membership-requests/{request.id}/revoke", {}, format="json")

    assert listed.status_code == 200, listed.data
    assert listed.data["results"] == []
    assert revoked.status_code == 400
    assert MembershipRequest.objects.get(pk=request.id).state == MembershipRequest.State.REQUESTED


def test_staff_invitation_survives_membership_off_end_to_end():
    space = _space("d3-staff-invite")
    manager = _manager(space, "d3-staff-invite-manager")
    disable_module(space, "membership")
    invitee = _user("d3-staff-invitee")
    staff_role = _role(space, "inventory_manager")

    invitation = membership_services.invite_membership(manager, space, invitee.email, staff_role)
    claimed = membership_services.claim_invitation(invitee, invitation.pk)
    listed = _client(manager).get("/api/v1/admin/membership-requests", {"makerspace_id": space.pk})
    approved = _client(manager).post(
        f"/api/v1/admin/membership-requests/{invitation.pk}/approve",
        {"role_id": staff_role.pk},
        format="json",
    )

    assert claimed.pk == invitation.pk
    assert listed.status_code == 200, listed.data
    assert [row["id"] for row in listed.data["results"]] == [invitation.pk]
    assert approved.status_code == 200, approved.data
    membership = MakerspaceMembership.objects.get(makerspace=space, user=invitee)
    assert (membership.status, membership.assigned_role_id) == ("active", staff_role.pk)
