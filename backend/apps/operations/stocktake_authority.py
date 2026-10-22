"""Who may approve and apply a completed stocktake."""

from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User


def can_review_stocktake(actor, stocktake) -> bool:
    """Approve/apply authority for one stocktake (both steps use the same rule).

    Superadmins may always review. A holder of manage_makerspace in the stocktake's
    makerspace (a Space Manager) may review someone else's count, never one they
    completed themselves -- the count and its sign-off need two people. A row with no
    recorded completer predates that field, so the four-eyes rule cannot be checked and
    it stays superadmin-only.
    """
    if actor is None or not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, stocktake.makerspace_id):
        return False
    if _global_superadmin_in(actor, stocktake.makerspace_id):
        return True
    return stocktake.completed_by_id is not None and stocktake.completed_by_id != actor.pk


def require_stocktake_reviewer(actor, stocktake):
    if not can_review_stocktake(actor, stocktake):
        raise PermissionDenied(
            "Approving or applying this stocktake needs manage_makerspace, and a "
            "different person from the one who completed it."
        )


def _global_superadmin_in(actor, makerspace_id):
    # In a hard-hidden makerspace a superadmin acts only through their membership, so
    # the four-eyes rule applies to them there like any Space Manager.
    return (actor.is_superuser or actor.role == User.Role.SUPERADMIN) and (
        makerspace_id not in rbac.superadmin_hidden_makerspace_ids()
    )
