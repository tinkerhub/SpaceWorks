"""Admit every tenant a walk-in transition's claim hooks can write."""

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar

from rest_framework.exceptions import APIException

from apps.makerspaces.models import MakerspaceMembership
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_locks import _retained_shared_lock_keys
from apps.tenant_migration.gate_runtime import _boundary_shared_locks, boundary_tenant_write

_admitted_transition = ContextVar("claim_transition_admission", default=None)


class ClaimTransitionScopeChanged(APIException):
    status_code = 409
    default_code = "identity_scope_changed"
    default_detail = "This identity's makerspace scope changed. Please retry."


def _membership_makerspace_ids(user_id):
    # All statuses count: revoked memberships can still own claims and presence.
    return frozenset(
        MakerspaceMembership.objects.filter(user_id=user_id)
        .values_list("makerspace_id", flat=True)
    )


@contextmanager
def claim_transition_gate(user_id):
    """Enter before row locks and outside the caller's outer atomic block.

    A pre-existing SQL transaction retains boundary_tenant_write's transaction locks
    through its real commit. Otherwise the boundary surrounds that commit itself.
    Nested transitions reuse exactly this admission; they must never discover or
    acquire another tenant while the outer caller already holds identity row locks.
    """
    admitted = _admitted_transition.get()
    if admitted is not None:
        if admitted[0] != user_id:
            raise SourceMigrationGateUnavailable("A different identity transition is active.")
        yield
        return

    makerspace_ids = _membership_makerspace_ids(user_id)
    # Held keys constrain ordering only. DB memberships still define admission,
    # including inactive/revoked links; P=0 never proves tenant admission.
    held_ids = (_retained_shared_lock_keys() | frozenset(_boundary_shared_locks.get())) - {0}
    new_ids = makerspace_ids - held_ids
    if new_ids and held_ids and min(new_ids) < max(held_ids):
        raise SourceMigrationGateUnavailable(
            "Retry this identity transition from the central administration origin "
            "to preserve makerspace lock order."
        )
    with ExitStack() as locks:
        for makerspace_id in sorted(makerspace_ids):
            locks.enter_context(boundary_tenant_write(makerspace_id))
        token = _admitted_transition.set((user_id, makerspace_ids))
        try:
            yield
        finally:
            _admitted_transition.reset(token)


def assert_claim_transition_scope(user_id):
    """Fresh check immediately after User FOR UPDATE, before any transition writes.

    That row lock serializes new membership FK inserts at commit. Growth since the
    unlocked preflight must retry from outside all row locks; shrinking is safe.
    """
    admitted = _admitted_transition.get()
    if admitted is None or admitted[0] != user_id:
        raise SourceMigrationGateUnavailable("The identity transition has no source admission.")
    if not _membership_makerspace_ids(user_id).issubset(admitted[1]):
        raise ClaimTransitionScopeChanged()
