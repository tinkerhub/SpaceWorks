"""Fresh, read-only outcome authority for destructive rollback cleanup."""

from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.object_restore_versions import ObjectRestoreError


class RollbackCleanupOutcomeUnavailable(ObjectRestoreError):
    def __init__(self):
        super().__init__("Rollback cleanup requires a confirmed terminal restore and normal recovery state.")


def require_cleanup_outcome(restore_id):
    # Do not use load(): a missing singleton is missing proof, not normal mode.
    state = DeploymentRecoveryState.objects.filter(pk=1).only("mode", "active_restore_id").first()
    cleanable = {RestoreOperation.Stage.COMPLETED, RestoreOperation.Stage.RESTORED_QUARANTINED}
    if state is None or state.mode != DeploymentRecoveryState.Mode.NORMAL:
        raise RollbackCleanupOutcomeUnavailable()
    restore = RestoreOperation.objects.filter(pk=restore_id).only("stage").first()
    if restore is None or restore.stage not in cleanable:
        # FAILED + NORMAL does not prove that rollback restored the original bytes.
        raise RollbackCleanupOutcomeUnavailable()
    if state.active_restore_id is not None:
        active_stage = RestoreOperation.objects.filter(pk=state.active_restore_id).values_list("stage", flat=True).first()
        if active_stage not in cleanable:
            raise RollbackCleanupOutcomeUnavailable()
    # An acknowledged quarantine may intentionally retain its active pointer.
    return restore
