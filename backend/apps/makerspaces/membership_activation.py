"""The one row-locked path that turns a person into an active member."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MembershipRequest,
)


def is_community_request(request, role):
    """Whether a membership request belongs to the `membership` module.

    A join request always does. An invitation is discriminated by the role it activates,
    exactly as `invite_membership` discriminates it: a role granting no actions (the
    protected Member role included) is community membership; a role granting actions is
    a staff invitation, which must keep working with `membership` off.
    """
    if request.kind == MembershipRequest.Kind.REQUEST:
        return True
    return role is None or not role.granted_actions


def require_membership_module(makerspace):
    """Refuse a community membership change; call it with the makerspace row LOCKED."""
    if not module_enabled(makerspace, "membership"):
        raise ValidationError({"module": "membership is disabled for this makerspace."})


def _activate_membership(actor, makerspace, user, role, *, request=None, source):
    """Activate or reactivate exactly one membership in the mandated lock order."""
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        driving_request = None
        if request is not None:
            driving_request = MembershipRequest.objects.select_for_update().get(pk=request.pk)
            if driving_request.makerspace_id != makerspace.pk:
                raise ValidationError({"detail": "Membership request is for another makerspace."})
            if driving_request.state not in (
                MembershipRequest.State.REQUESTED,
                MembershipRequest.State.INVITED,
            ):
                raise ValidationError({"detail": "This membership request is no longer open."})
            if driving_request.user_id not in (None, user.pk):
                raise ValidationError({"detail": "Membership request belongs to another account."})
            if is_community_request(driving_request, role):
                # Under the makerspace lock module_install also takes, so an uninstall
                # cannot slip between the view's check and the activation. Staff
                # invitations are core RBAC and are deliberately not gated (plan A7).
                require_membership_module(makerspace)
            if driving_request.user_id is None:
                driving_request.user = user
                driving_request.save(update_fields=["user", "updated_at"])
        if source == "claim":
            audit.record(actor, "membership.invitation_claimed", makerspace=makerspace,
                         target=driving_request)
            return driving_request

        membership = MakerspaceMembership.objects.select_for_update().filter(
            makerspace=makerspace, user=user
        ).first()
        role = MakerspaceRole.objects.select_for_update().get(pk=role.pk)
        if role.makerspace_id != makerspace.pk:
            raise ValidationError({"role_id": "Role must belong to this makerspace."})

        adding = membership is None or membership.status != "active"
        if adding:
            limits.check_quota(makerspace, "members", adding=1)

        now = timezone.now()
        if membership is None:
            membership = MakerspaceMembership.objects.create(
                makerspace=makerspace,
                user=user,
                assigned_role=role,
                role=role.legacy_role or MakerspaceMembership.Role.CUSTOM,
                status="active",
                activated_at=now,
                activated_by=actor,
            )
        elif adding:
            membership.assigned_role = role
            membership.role = role.legacy_role or MakerspaceMembership.Role.CUSTOM
            membership.status = "active"
            membership.activated_at = now
            membership.activated_by = actor
            membership.revoked_at = None
            membership.revoked_by = None
            membership.revocation_reason = ""
            # A revoked row may predate the delegation-clearing revoke path.
            # Reactivation must never restore referral or verifier authority.
            membership.can_refer = False
            membership.can_verify = False
            membership.save()
        elif source == "approval":
            membership.assigned_role = role
            membership.role = role.legacy_role or MakerspaceMembership.Role.CUSTOM
            membership.save(update_fields=["assigned_role", "role"])

        open_requests = list(MembershipRequest.objects.select_for_update().filter(
            makerspace=makerspace,
            state__in=[MembershipRequest.State.REQUESTED, MembershipRequest.State.INVITED],
        ).filter(Q(user=user) | Q(invite_email=(user.email or "").strip().lower())))
        for item in open_requests:
            item.state = MembershipRequest.State.ACTIVE
            item.decided_by = actor
            item.decided_at = now
            fields = ["state", "decided_by", "decided_at", "updated_at"]
            if item.pk == getattr(driving_request, "pk", None):
                item.assigned_role = role
                fields.insert(0, "assigned_role")
            item.save(update_fields=fields)

        if adding or source == "approval" or open_requests:
            action = "membership.approved" if source == "approval" else "membership.joined"
            meta = {"role_id": role.id, "source": source}
            if driving_request is not None:
                meta["request_id"] = driving_request.pk
            audit.record(actor, action, makerspace=makerspace, target=membership, meta=meta)
            if source == "approval":
                audit.record(actor, "membership.role_changed", makerspace=makerspace,
                             target=membership, meta={"role_id": role.id})
        if adding:
            from apps.makerspaces.membership_notifications import (
                notify_member_joined,
                send_member_welcome,
            )
            send_member_welcome(membership, source=source)
            notify_member_joined(membership)
            from apps.makerspaces.membership_payments import (
                create_for_active_membership,
            )

            create_for_active_membership(membership, actor)
        return membership
