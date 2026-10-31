"""Fresh deployment-wide admission for ordinary background work."""

from django.db import DatabaseError


class DeploymentRecoveryTaskBlocked(RuntimeError):
    """Recovery state has not proved that ordinary task work is safe."""


def assert_background_work_allowed():
    # Do not use load(): a missing singleton must refuse work, never create NORMAL.
    # Query the primary on every invocation, before tenant resolvers can read rows
    # whose integer IDs may now refer to a restored source database.
    from apps.backup.models import DeploymentRecoveryState

    try:
        mode = (
            DeploymentRecoveryState.objects.using("default")
            .filter(pk=1)
            .values_list("mode", flat=True)
            .first()
        )
    except DatabaseError:
        # Driver exceptions can contain connection details. Keep task errors fixed.
        raise DeploymentRecoveryTaskBlocked(
            "Background work refused: deployment recovery state is unreadable."
        ) from None
    if mode != DeploymentRecoveryState.Mode.NORMAL:
        raise DeploymentRecoveryTaskBlocked(
            "Background work refused: deployment recovery state is not normal."
        )
