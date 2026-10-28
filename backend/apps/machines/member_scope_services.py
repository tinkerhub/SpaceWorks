"""Write boundary for one member's personal machine-type links.

The per-person twin of ``role_scope_services``: same authority (``MANAGE_MAKERSPACE``,
revalidated under locks), same replace-wholesale semantics, same refusal to drop an
unknown id silently. Lives in ``apps.machines`` for the same tombstoning reason.
"""

from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces import role_services

from .models_member_scope import MembershipMachineTypeScope
from .models_role_scope import RoleMachineTypeScope
from .role_scope_resolution import EXEMPT, _scope_for_membership
from .role_scope_services import _validated_ids, assignable_machine_types


def personal_type_ids(membership):
    return sorted(
        MembershipMachineTypeScope.objects.filter(membership=membership).values_list(
            "machine_type_id", flat=True
        )
    )


def member_scope_payload(makerspace, membership):
    """Personal links, what the role already covers, and every assignable type."""
    # EXEMPT, NOTHING (tenant-mismatched role) or None with the role id to read links for.
    exempt_or_nothing, role_id = _scope_for_membership(membership)
    # Through `actions_for_membership`, so a legacy null-role membership is judged by its
    # fallback actions rather than called "covers everything" when it manages no machine.
    grants_machines = rbac.Action.MANAGE_MACHINES in rbac.actions_for_membership(membership)
    return {
        "machine_type_ids": personal_type_ids(membership),
        "role_machine_type_ids": sorted(
            RoleMachineTypeScope.objects.filter(role_id=role_id).values_list(
                "machine_type_id", flat=True
            )
        ) if role_id is not None else [],
        "available_machine_types": [
            {"id": row.pk, "label": row.name, "is_builtin": row.is_builtin}
            for row in assignable_machine_types(makerspace)
        ],
        # Personal links only widen a role-scoped MANAGE_MACHINES grant. For an exempt
        # member (space manager, legacy fallback) or a role without that grant they change
        # nothing, and the console must say so rather than offer boxes that do nothing.
        "scoping_applies": exempt_or_nothing is None and grants_machines,
        "role_covers_all": exempt_or_nothing is EXEMPT and grants_machines,
    }


@transaction.atomic
def set_member_machine_scope(*, makerspace, membership, actor, machine_type_ids):
    """Replace the member's personal type links wholesale.

    Locks the makerspace first, as every role and membership mutation does, so this cannot
    deadlock against a concurrent role edit or role assignment on the same member.
    """
    from apps.makerspaces.models import Makerspace, MakerspaceMembership

    # FOR NO KEY UPDATE for the reason documented in `set_role_machine_scope`.
    makerspace = Makerspace.objects.select_for_update(no_key=True).get(pk=makerspace.pk)
    actor_actions = role_services._locked_actor_actions(actor, makerspace)
    if rbac.Action.MANAGE_MAKERSPACE not in actor_actions:
        raise PermissionDenied()
    membership = (
        MakerspaceMembership.objects.select_for_update(of=("self",))
        .select_related("assigned_role", "user")
        .get(pk=membership.pk, makerspace=makerspace)
    )

    type_ids = _validated_ids(
        machine_type_ids, assignable_machine_types(makerspace), "machine_type_ids"
    )
    before = personal_type_ids(membership)
    MembershipMachineTypeScope.objects.filter(membership=membership).exclude(
        machine_type_id__in=type_ids
    ).delete()
    MembershipMachineTypeScope.objects.bulk_create(
        [
            MembershipMachineTypeScope(membership=membership, machine_type_id=type_id)
            for type_id in sorted(type_ids)
        ],
        ignore_conflicts=True,
    )
    after = personal_type_ids(membership)
    if after != before:
        # A permission boundary in its own right, like `role.machine_scope_changed`.
        audit.record(
            actor,
            "membership.machine_scope_changed",
            makerspace=makerspace,
            target=membership.user,
            meta={"membership_id": membership.pk, "before": before, "after": after},
        )
    return membership
