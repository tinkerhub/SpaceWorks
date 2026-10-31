"""Fixed maintenance SQL facts for root-controlled in-place marker release."""

from datetime import datetime

from .host_marker import MarkerError


ACKNOWLEDGEMENT = (
    "I understand that this blanket acknowledgement may restore authority removed after "
    "the archive was created. On a disaster restore, the destroyed live database cannot "
    "be compared and identity links may have been reintroduced."
)
FIELDS = (
    "mode", "active_restore", "stage", "decision", "acknowledged_at",
    "acknowledged_by", "recovery_principal", "acknowledgement",
)


def query_recovery_proof(database, restore_id):
    """Read an existing singleton and exact operation; never create default state."""
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT state.mode, state.active_restore_id::text, operation.stage, "
            "operation.decision, state.acknowledged_at, state.acknowledged_by_id, "
            "state.recovery_principal_id, state.acknowledgement "
            "FROM public.backup_deploymentrecoverystate state "
            "CROSS JOIN public.backup_restoreoperation operation "
            "WHERE state.id = 1 AND operation.id = %s", [restore_id],
        )
        rows = cursor.fetchmany(2)
    if len(rows) != 1:
        raise MarkerError("The exact existing recovery state and operation are required.")
    result = dict(zip(FIELDS, rows[0], strict=True))
    if result["acknowledged_at"] is not None:
        result["acknowledged_at"] = result["acknowledged_at"].isoformat()
    return result


def validate_recovery_proof(proof, restore_id, *, acknowledgement):
    if not isinstance(proof, dict) or set(proof) != set(FIELDS):
        raise MarkerError("In-place restore recovery proof has an invalid shape.")
    if acknowledgement:
        try:
            stamp = datetime.fromisoformat(proof["acknowledged_at"])
            valid_stamp = stamp.tzinfo is not None
        except (ValueError, TypeError):
            valid_stamp = False
        if not (
            proof["mode"] == "normal" and proof["active_restore"] == restore_id
            and proof["stage"] == "restored_quarantined" and valid_stamp
            and type(proof["recovery_principal"]) is int and proof["recovery_principal"] > 0
            and proof["acknowledged_by"] == proof["recovery_principal"]
            and proof["acknowledgement"] == ACKNOWLEDGEMENT
            and proof["decision"] in {"proceed", "reset"}
        ):
            raise MarkerError("The recovered principal has not acknowledged this exact restore.")
        return "acknowledged"
    if (
        proof["mode"] == "quarantined" and proof["active_restore"] == restore_id
        and proof["stage"] == "restored_quarantined" and proof["decision"] in {"proceed", "reset"}
        and proof["acknowledged_at"] is None and proof["acknowledged_by"] is None
        and proof["acknowledgement"] == ""
    ):
        return "quarantined"
    if (
        proof["mode"] == "normal" and proof["active_restore"] is None
        and proof["stage"] == "completed" and proof["decision"] == "proceed"
    ):
        return "normal"
    raise MarkerError("The exact restore has not reached a verified successful recovery state.")
