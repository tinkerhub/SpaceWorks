"""Resolve role-linked machine scopes and test their coverage."""

from collections import defaultdict

from apps.accounts import rbac
from apps.accounts.rbac import Action

from .models_member_scope import MembershipMachineTypeScope
from .models_role_scope import RoleMachineScope, RoleMachineTypeScope


# Scoping does not restrict this actor here. A distinct object rather than None/True so a
# caller cannot confuse "unrestricted" with "restricted to nothing" -- the two are
# opposites and both are falsy in the shapes we would otherwise reach for.
EXEMPT = object()

# The fail-closed answer: a role that holds MANAGE_MACHINES but has no links.
NOTHING = (frozenset(), frozenset())


def _scope_for_membership(membership):
    """EXEMPT, a role id to look links up for, or NOTHING. No queries beyond the FK."""
    if membership.assigned_role_id is None:
        # The frozen legacy fallback (`rbac._MEMBERSHIP_ROLE_ACTIONS`) is not a role row,
        # so there is nothing to hang links on. Scoping it would silently strip a legacy
        # Machine Manager of every machine at upgrade time, which is precisely the
        # regression the backfill exists to prevent.
        return EXEMPT, None
    role = membership.assigned_role
    if role.makerspace_id != membership.makerspace_id:
        # Same tenant-mismatch fail-closed rule as `rbac.actions_for_membership`.
        return NOTHING, None
    granted = role.granted_actions if isinstance(role.granted_actions, list) else []
    if Action.MANAGE_MAKERSPACE in rbac.expand_implied_actions(
        action for action in granted if isinstance(action, str)
    ):
        # Locked decision: a space manager always covers every machine, including types
        # that do not exist yet. Making them enumerate types to keep administering their
        # own lab is a worse failure than the broad grant this mechanism narrows.
        return EXEMPT, None
    return None, role.pk


def _role_links(role_ids):
    """``(types, machines)``: role id -> linked id sets. Two queries for any number of roles."""
    types = defaultdict(set)
    machines = defaultdict(set)
    for role_id, type_id in RoleMachineTypeScope.objects.filter(
        role_id__in=role_ids
    ).values_list("role_id", "machine_type_id"):
        types[role_id].add(type_id)
    for role_id, machine_id in RoleMachineScope.objects.filter(
        role_id__in=role_ids
    ).values_list("role_id", "machine_id"):
        machines[role_id].add(machine_id)
    return types, machines


def _personal_types(membership_ids):
    """Membership id -> personal type ids (``models_member_scope``). One query."""
    personal = defaultdict(set)
    for membership_id, type_id in MembershipMachineTypeScope.objects.filter(
        membership_id__in=membership_ids
    ).values_list("membership_id", "machine_type_id"):
        personal[membership_id].add(type_id)
    return personal


def manage_scopes_for(actor, makerspace_ids):
    """Map each makerspace id to EXEMPT or ``(type_ids, machine_ids)``.

    Three queries regardless of how many makerspaces are asked about, because the callers
    that matter are list endpoints -- resolving this per row would put an N+1 behind
    every machine list in the console.

    A role-scoped membership reaches its role's links PLUS its own personal type links.
    Personal links only ever join that branch: an EXEMPT or NOTHING answer is decided by
    the role before they are read, so they can neither narrow a space manager nor revive
    a tenant-mismatched role.

    A makerspace with no membership row resolves to EXEMPT for a superadmin (their grant
    does not come from a role, so no role can scope it) and to NOTHING otherwise. The
    latter is unreachable through the normal callers, which only ask about makerspaces
    where ``MANAGE_MACHINES`` is already granted, but it is the safe answer if it ever is.
    """
    ids = {ms_id for ms_id in makerspace_ids if ms_id is not None}
    ids -= rbac.archived_makerspace_ids()
    if not ids or actor is None or not getattr(actor, "is_authenticated", False):
        return {}

    resolved = {}
    scoped = []
    memberships = actor.makerspace_memberships.select_related("assigned_role").filter(
        status="active", makerspace_id__in=ids
    )
    for membership in memberships:
        answer, role_id = _scope_for_membership(membership)
        if answer is not None:
            resolved[membership.makerspace_id] = answer
        else:
            scoped.append((membership, role_id))

    if scoped:
        types, machines = _role_links([role_id for _, role_id in scoped])
        personal = _personal_types([membership.pk for membership, _ in scoped])
        for membership, role_id in scoped:
            resolved[membership.makerspace_id] = (
                frozenset(types[role_id] | personal[membership.pk]),
                frozenset(machines[role_id]),
            )

    superadmin = rbac._is_superadmin(actor)
    for ms_id in ids - set(resolved):
        resolved[ms_id] = EXEMPT if superadmin else NOTHING
    return resolved


def manage_scope_for(actor, makerspace_id):
    """Single-makerspace form of :func:`manage_scopes_for`."""
    return manage_scopes_for(actor, [makerspace_id]).get(makerspace_id, NOTHING)


def manage_scopes_for_memberships(memberships):
    """Map membership id -> EXEMPT or ``(type_ids, machine_ids)``.

    The membership-keyed twin of :func:`manage_scopes_for`, for callers that already hold
    the rows and would otherwise resolve one actor at a time. Notification recipient
    resolution is exactly that shape: it has already selected the memberships and needs
    each one's machine reach, so a per-actor call would put an N+1 behind every alert.

    Three link queries regardless of how many memberships are passed, and the same answers
    as the per-actor path -- it is the same `_scope_for_membership`, `_role_links` and
    `_personal_types` underneath, so the two cannot drift.
    """
    memberships = list(memberships)
    resolved = {}
    role_to_memberships = defaultdict(list)
    for membership in memberships:
        answer, role_id = _scope_for_membership(membership)
        if answer is not None:
            resolved[membership.pk] = answer
        else:
            role_to_memberships[role_id].append(membership.pk)

    if role_to_memberships:
        types, machines = _role_links(list(role_to_memberships))
        personal = _personal_types(
            [pk for membership_ids in role_to_memberships.values() for pk in membership_ids]
        )
        for role_id, membership_ids in role_to_memberships.items():
            for membership_id in membership_ids:
                resolved[membership_id] = (
                    frozenset(types[role_id] | personal[membership_id]),
                    frozenset(machines[role_id]),
                )
    return resolved


def scope_covers_machine(scope, machine):
    """Whether a resolved scope reaches one machine. Pure -- no queries."""
    if scope is EXEMPT:
        return True
    type_ids, machine_ids = scope
    return machine.pk in machine_ids or machine.machine_type_id in type_ids


def scope_covers_type(scope, machine_type):
    """Whether a resolved scope reaches a whole type.

    Used for creation, where there is no machine yet to check. A per-machine link cannot
    answer this -- it names a machine that does not exist -- so only a type link grants
    the right to add a machine of that type.
    """
    if scope is EXEMPT:
        return True
    if machine_type is None:
        return False
    type_ids, _ = scope
    type_id = getattr(machine_type, "pk", machine_type)
    return type_id in type_ids


def covers_machine(actor, machine):
    """Whether the actor's role scope reaches this machine. Assumes the grant is held."""
    return scope_covers_machine(manage_scope_for(actor, machine.makerspace_id), machine)


def covers_type(actor, makerspace_id, machine_type):
    """Whether the actor's role scope reaches this type. Assumes the grant is held."""
    return scope_covers_type(manage_scope_for(actor, makerspace_id), machine_type)
