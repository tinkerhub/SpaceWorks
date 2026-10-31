#!/usr/bin/env python3
"""One root controller and operation lock across import, restore, and acknowledgement."""

import argparse
import os
from pathlib import Path
import signal
import stat
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from apps.backup.host_marker import MarkerState, read_marker
from apps.backup.host_restore_admission import admit_configuration, inventory, target_identity
from apps.backup.host_restore_lifecycle import InplaceRestore, fixed_probe
from apps.backup.host_restore_prepare import RestoreInputs
from apps.backup.host_restore_resume import recover_principal, resume_host
from apps.backup.host_restore_transport import RestoreHostError, RestoreTransport
from apps.backup.operation_lock import host_operation_lock


def interrupted(_signal, _frame):
    raise RestoreHostError("Host restore interrupted; recovery evidence and writer fencing retained.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("restore_id", type=uuid.UUID)
    imported = commands.add_parser("import")
    imported.add_argument("source", type=Path)
    imported.add_argument("username")
    imported.add_argument("expected_sha256", nargs="?")
    resumed = commands.add_parser("resume-host")
    resumed.add_argument("restore_id", type=uuid.UUID)
    recovered = commands.add_parser("recover-superadmin")
    recovered.add_argument("restore_id", type=uuid.UUID)
    recovered.add_argument("username")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RestoreHostError("In-place restore requires the installed root-owned Linux host controller.")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    transport = RestoreTransport(ROOT)
    with host_operation_lock(transport.ops, require_root_owned=True) as lock:
        held = os.fstat(lock.fileno())
        recorded = (transport.ops / "operation.lock").stat(follow_symlinks=False)
        if (not stat.S_ISREG(recorded.st_mode) or recorded.st_uid != 0 or recorded.st_nlink != 1
                or (held.st_dev, held.st_ino) != (recorded.st_dev, recorded.st_ino)):
            raise RestoreHostError("The shared host operation lock inode is untrusted.")
        # Every later child closes inherited FDs. This process never execs a service.
        if args.command == "resume-host":
            return resume_host(transport, lock, str(args.restore_id))
        if args.command == "recover-superadmin":
            return recover_principal(transport, str(args.restore_id), args.username)
        marker = read_marker(transport.host / "public/restore-marker.json")
        if marker.state not in {MarkerState.NORMAL, MarkerState.ACKNOWLEDGED_NORMAL} or marker.operation:
            raise RestoreHostError("The host is already fenced; automatic destructive replay is unavailable.")
        if marker.reservations or marker.fences or marker.not_restored:
            raise RestoreHostError("Protected compound target declarations require their coordinator; in-place restore is refused before effects.")
        admit_configuration(transport)
        inventory(transport)
        identity = target_identity(transport)
        if fixed_probe(transport)["recovery_state"] != {"mode": "normal", "active_restore": None}:
            raise RestoreHostError("An existing NORMAL recovery singleton with no active restore is required before effects.")
        if args.command == "restore":
            identifier = str(args.restore_id)
            if (transport.ops / "work" / f"restore-{identifier}" / "destructive-started").exists():
                raise RestoreHostError("A historical interrupted destructive operation requires manual recovery; no rollback or restart was attempted.")
            inputs = RestoreInputs(transport, restore_id=identifier)
        else:
            inputs = RestoreInputs(transport, source=args.source, username=args.username, expected=args.expected_sha256)
        operation = InplaceRestore(transport, lock, inputs, identity)
        try:
            decision = operation.decision()
            if decision is not None:
                operation.restore(decision)
        except BaseException:
            operation.retain_failure()
            raise


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        # Driver/Compose/env errors can contain secrets. Detailed bytes remain private.
        if isinstance(exc, RestoreHostError):
            print(str(exc), file=sys.stderr)
        print("SpaceWorks restore refused or interrupted. No automatic rollback, key reversal, "
              "writer release or evidence deletion was performed. Retain the root-private "
              "operation records and consult the manual recovery runbook.", file=sys.stderr)
        raise SystemExit(1) from None
