"""Explicit successful-quarantine acknowledgement; no failed-restore unblock path."""

import json
from pathlib import Path
import re
import subprocess

from .host_marker import MarkerState, read_marker
from .host_restore_admission import admit_configuration, inventory, reuse_redis_admission, target_identity
from .host_restore_configuration import verify_installed_configuration
from .host_restore_lifecycle import fixed_probe, marker_controller, stop_current_writers
from .host_restore_transport import RestoreHostError, trusted
from .host_run_ledger import RunLedger
from .inplace_recovery_facts import validate_recovery_proof


def resume_host(transport, lock, restore_id):
    marker = read_marker(transport.host / "public/restore-marker.json")
    if marker.state != MarkerState.QUARANTINED_AFTER_CUTOVER or marker.operation.restore_id != restore_id:
        raise RestoreHostError("Host resume requires this exact successfully quarantined restore.")
    index = json.loads(trusted(transport.ops / "private" / f"inplace-index-{restore_id}.json", private=True).read_bytes())
    private = Path(index["private"])
    if private.parent != transport.ops / "private":
        raise RestoreHostError("The private operation index is outside the trusted operation directory.")
    trusted(private, private=True, directory=True)
    hashes = verify_installed_configuration(transport, private)
    admit_configuration(transport)
    reuse_redis_admission(transport, private)
    inventory(transport, stopped=True, allow_backend=True)
    live = target_identity(transport)
    proof = fixed_probe(transport, restore_id)["recovery_proof"]
    ledger = RunLedger(transport.ops / "runs" / f"{restore_id}.jsonl", run_id=restore_id,
                       artifact_sha256=marker.operation.artifact_sha256)
    controller = marker_controller(transport, lock, ledger, private)
    controller.acknowledge(marker.operation, live, proof,
        configuration_sha256=hashes[0], topology_sha256=hashes[1])
    try:
        transport.compose("up", "-d", "--no-deps", "worker", "beat")
        inventory(transport)
    except BaseException:
        controller.block_failed_start(marker.operation, live,
            configuration_sha256=hashes[0], topology_sha256=hashes[1])
        stop_current_writers(transport)
        raise
    print("Recovered-principal acknowledgement and successful root phases verified; host writers resumed.", flush=True)


def recover_principal(transport, restore_id, username):
    marker = read_marker(transport.host / "public/restore-marker.json")
    if (marker.state != MarkerState.QUARANTINED_AFTER_CUTOVER or marker.operation.restore_id != restore_id
            or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@+-]{0,149}", username)):
        raise RestoreHostError("Recovery principal command requires an exact quarantined restore and existing username.")
    index = json.loads(trusted(transport.ops / "private" / f"inplace-index-{restore_id}.json", private=True).read_bytes())
    private = Path(index["private"])
    if private.parent != transport.ops / "private":
        raise RestoreHostError("Recovery principal operation index is outside the trusted root.")
    trusted(private, private=True, directory=True)
    hashes = verify_installed_configuration(transport, private)
    admit_configuration(transport)
    reuse_redis_admission(transport, private)
    inventory(transport, stopped=True, allow_backend=True)
    live = target_identity(transport)
    ledger = RunLedger(transport.ops / "runs" / f"{restore_id}.jsonl", run_id=restore_id,
                       artifact_sha256=marker.operation.artifact_sha256)
    # A successful quarantine receipt is required even for this fixed management exec.
    record = json.loads(trusted(private / "marker-operation.json", private=True).read_bytes())
    terminal = [event for event in ledger.records() if event["phase"] == "inplace-terminal" and event["state"] == "done"]
    if (len(terminal) != 1 or terminal[0]["detail"] != {"binding": record["binding"], "outcome": "quarantined"}
            or record["binding"]["configuration_sha256"] != hashes[0]
            or record["binding"]["topology_sha256"] != hashes[1]):
        raise RestoreHostError("Recovery principal requires this exact successful root quarantine receipt.")
    validate_recovery_proof(fixed_probe(transport, restore_id)["recovery_proof"], restore_id, acknowledgement=False)
    # Password output goes only to the operator terminal, never to a root receipt.
    result = subprocess.run([str(transport.root / "scripts/spaceworks-compose.sh"), "bundled",
        "exec", "-T", "backend", "python", "manage.py", "recover_superadmin", username],
        cwd=transport.root, env=transport.environment, close_fds=True, check=False)
    if result.returncode:
        raise RestoreHostError("The fixed quarantined recovery-principal command failed.")
