"""Private Stage3 fixtures. No production ACL or authority check is replaced here."""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import uuid

from apps.backup.host_capability_journal import CapabilityJournal
from apps.backup.host_marker import DatabaseIdentity, MarkerState, OperationIdentity, marker_payload, write_marker_fsynced
from apps.backup.host_pointer import PointerRecord, write_pointer_atomic
from apps.backup.host_run_ledger import RunLedger
from apps.backup.host_supervisor import HostMarkerTransition
from apps.backup.inplace_marker import InplaceMarkerTransition, VERIFIED_PHASES, phase_binding
from apps.backup.operation_lock import host_operation_lock


RESTORE_ID = "4511b438-1234-4c35-89ab-0123456789ab"
ARTIFACT = "a" * 64
CONFIG = "b" * 64
TOPOLOGY = "c" * 64


def repo_root():
    explicit = os.environ.get("SPACEWORKS_TEST_REPO_ROOT")
    candidates = [Path(explicit)] if explicit else [Path(__file__).resolve().parents[3], Path("/repo")]
    for path in candidates:
        if path != Path("/") and (path / "scripts/restore.sh").is_file() and (path / "AGENTS.md").is_file():
            return path.resolve()
    raise AssertionError("Mount the full checkout at /repo and set SPACEWORKS_TEST_REPO_ROOT=/repo; backend-only /app is insufficient.")


def require_linux_root():
    assert sys.platform == "linux" and os.geteuid() == 0, (
        "Run this lane on Linux as UID0; actual root ownership/chown/flock is part of its proof."
    )


def private(path, payload):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    path.chmod(0o600)
    return path


def target_identity():
    return DatabaseIdentity("recovery_target", 16384, {
        "endpoint": {"host": "db", "port": 5432, "database": "recovery_target", "tls_identity": ""},
        "database_uuid": "670a9c81-1234-4aaa-8c81-0123456789ab", "system_identifier": "7400000000000000001",
    })


def recovery_proof(*, acknowledged=False, normal=False):
    from apps.backup.inplace_recovery_facts import ACKNOWLEDGEMENT

    return {"mode": "normal" if normal or acknowledged else "quarantined",
        "active_restore": None if normal else RESTORE_ID,
        "stage": "completed" if normal else "restored_quarantined", "decision": "proceed",
        "acknowledged_at": "2026-10-30T12:00:00+00:00" if acknowledged else None,
        "acknowledged_by": 42 if acknowledged else None, "recovery_principal": 42 if acknowledged else None,
        "acknowledgement": ACKNOWLEDGEMENT if acknowledged else ""}


def archive_row(**kwargs):
    """Insert valid inputs once; never mutate past an archive immutability guard."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.backup.models import BackupArchive

    values = {"scope": "deployment", "status": "available", "age_encrypted": True,
        "expires_at": timezone.now() + timedelta(days=1),
        "object_key": "backup-archives/stage3/" + uuid.uuid4().hex + ".tar.age"}
    values.update(kwargs)
    return BackupArchive.objects.create(**values)


@dataclass
class MarkerRig:
    ops: Path
    marker: Path
    pointer: Path
    operation: OperationIdentity
    identity: DatabaseIdentity
    controller: InplaceMarkerTransition
    ledger: RunLedger
    lock: object

    def begin(self):
        return self.controller.begin(self.operation, self.identity, CONFIG, TOPOLOGY, "signed-full")

    def phases(self, names=VERIFIED_PHASES, *, binding=None):
        for name in names:
            detail = {"binding": binding or phase_binding(self.operation, CONFIG, TOPOLOGY), "evidence_sha256": "d" * 64}
            begun = self.ledger.begin(name, detail)
            self.ledger.finish(begun)

    def complete(self, proof=None):
        return self.controller.complete(self.operation, self.identity, proof or recovery_proof(),
            configuration_sha256=CONFIG, topology_sha256=TOPOLOGY)


@contextmanager
def marker_rig(tmp_path):
    require_linux_root()
    ops = tmp_path / "ops"
    ops.mkdir(mode=0o700)
    (ops / "runs").mkdir(mode=0o700)
    pointer = ops / "database-pointer.env"
    write_pointer_atomic(pointer, PointerRecord("postgres://app:secret@db:5432/recovery_target", 7))
    marker = tmp_path / "host/public/restore-marker.json"
    identity = target_identity()
    write_marker_fsynced(marker, marker_payload(MarkerState.NORMAL, identity))
    journal = CapabilityJournal(tmp_path / "host/private/capabilities.jsonl")
    journal.path.parent.mkdir(mode=0o700, exist_ok=True)
    transition = HostMarkerTransition(marker, journal)
    operation = OperationIdentity(RESTORE_ID, ARTIFACT, str(uuid.uuid4()), 7)
    ledger = RunLedger(ops / "runs" / (RESTORE_ID + ".jsonl"), run_id=RESTORE_ID, artifact_sha256=ARTIFACT)
    with host_operation_lock(ops, require_root_owned=True) as lock:
        (ops / "operation.lock").chmod(0o666)  # Installed shared inode; never authority bytes.
        controller = InplaceMarkerTransition(transition, lock, ledger, pointer, ops / "private/marker-operation.json")
        yield MarkerRig(ops, marker, pointer, operation, identity, controller, ledger, lock)
