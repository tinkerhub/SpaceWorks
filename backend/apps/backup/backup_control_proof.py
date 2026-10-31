"""Fixed read-only host proofs and restore object verification commands."""

import json
from pathlib import Path

from django.core.management.base import CommandError

from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.restore_object_proof import require_blocked_restore, verify_restored_objects, verify_source_closure


def add_proof_arguments(actions):
    command = actions.add_parser("host-proof")
    command.add_argument("restore_id")
    for name in ("verify-source-objects", "verify-restored-objects"):
        command = actions.add_parser(name)
        command.add_argument("restore_id")
        command.add_argument("--manifest", required=True)
        if name == "verify-restored-objects":
            command.add_argument("--journal", required=True)


def run_proof(action, options):
    if action not in {"host-proof", "verify-source-objects", "verify-restored-objects"}:
        return None
    restore = RestoreOperation.objects.get(pk=options["restore_id"])
    if action == "host-proof":
        state = DeploymentRecoveryState.objects.get(pk=1)
        return json.dumps({
            "mode": state.mode,
            "active_restore": str(state.active_restore_id) if state.active_restore_id else None,
            "stage": restore.stage, "decision": restore.decision,
            "acknowledged_at": state.acknowledged_at.isoformat() if state.acknowledged_at else None,
            "acknowledged_by": state.acknowledged_by_id,
            "recovery_principal": state.recovery_principal_id,
            "acknowledgement": state.acknowledgement,
        })
    try:
        manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8"))
        if manifest != restore.archive.manifest:
            raise CommandError("Object proof manifest differs from the selected registered archive.")
        if action == "verify-source-objects":
            require_blocked_restore(restore)
            if restore.stage != RestoreOperation.Stage.DB_RESTORING:
                raise CommandError("Source closure must precede new recovery references.")
            verify_source_closure(manifest)
            return "source-object-closure-ok"
        verify_restored_objects(restore, manifest, options["journal"])
        return "restored-objects-ok"
    except CommandError:
        raise
    except Exception as exc:
        raise CommandError("Restore object closure or streamed readback refused success.") from exc
