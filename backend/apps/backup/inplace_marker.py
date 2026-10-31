"""Root-controller marker transitions for a bounded, in-place restore only.

The controller supplies fresh SQL facts from its fixed maintenance transport. Phase
receipts are root ledger records, never app-readable control-file assertions.
"""

from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import stat

from .host_marker import MarkerError, MarkerState, marker_payload, parse_marker, read_marker
from .host_pointer import read_pointer
from .host_private_file import write_private_file_fsynced
from .inplace_recovery_facts import validate_recovery_proof


VERIFIED_PHASES = (
    "inplace-configuration-verified", "inplace-sql-restored",
    "inplace-objects-verified", "inplace-readiness-verified",
)


def _digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise MarkerError("In-place restore proof digest is invalid.")
    return value


def phase_binding(operation, configuration_sha256, topology_sha256):
    return {
        "operation": asdict(operation),
        "configuration_sha256": _digest(configuration_sha256),
        "topology_sha256": _digest(topology_sha256),
    }


class InplaceMarkerTransition:
    def __init__(self, marker_transition, lock_handle, ledger, pointer_path, record_path):
        self.transition = marker_transition
        self.lock_handle = lock_handle
        self.ledger = ledger
        self.pointer_path = Path(pointer_path)
        self.record_path = Path(record_path)
        self.require_root_owned = marker_transition.require_root_owned

    def _trusted(self, path, *, private=True):
        path = Path(path)
        item, parent = path.stat(follow_symlinks=False), path.parent.stat(follow_symlinks=False)
        if not stat.S_ISREG(item.st_mode) or not stat.S_ISDIR(parent.st_mode):
            raise MarkerError("In-place restore authority path is not a regular file.")
        if self.require_root_owned and (
            os.geteuid() != 0 or item.st_uid != 0 or parent.st_uid != 0
            or item.st_mode & (0o077 if private else 0o022)
            or parent.st_mode & (0o077 if private else 0o022)
        ):
            raise MarkerError("In-place restore authority path is not root-owned and protected.")

    def _locked(self, operation):
        descriptor = self.lock_handle.fileno()
        lock_path = self.ledger.path.parent.parent / "operation.lock"
        held, expected = os.fstat(descriptor), lock_path.stat(follow_symlinks=False)
        parent = lock_path.parent.stat(follow_symlinks=False)
        # The installed lock is deliberately shared mode 0666. Its bytes carry
        # no authority; ownership, protected directory and held inode do.
        if (not stat.S_ISREG(expected.st_mode) or expected.st_nlink != 1 or not stat.S_ISDIR(parent.st_mode)
                or (self.require_root_owned and (
                    os.geteuid() != 0 or held.st_uid != 0 or expected.st_uid != 0
                    or parent.st_uid != 0 or parent.st_mode & 0o022))):
            raise MarkerError("In-place restore operation lock is untrusted.")
        if (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
            raise MarkerError("In-place restore does not hold the shared operation lock.")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if self.ledger.run_id != operation.restore_id or self.ledger.artifact_sha256 != operation.artifact_sha256:
            raise MarkerError("In-place restore ledger belongs to another operation.")
        if read_pointer(self.pointer_path, require_root_owned=self.require_root_owned).generation != operation.pointer_generation:
            raise MarkerError("In-place restore pointer generation changed.")
        if self.ledger.path.exists():
            self._trusted(self.ledger.path)

    def _marker(self):
        return read_marker(self.transition.marker_path, require_root_owned=self.require_root_owned)

    @staticmethod
    def _live(live_database, expected):
        if live_database != expected or live_database.server_identity is None:
            raise MarkerError("In-place restore live target identity changed.")

    def _read_record(self, operation):
        self._locked(operation)
        self._trusted(self.record_path)
        try:
            with self.record_path.open(encoding="utf-8") as stream:
                record = json.load(stream)
        except (OSError, ValueError, UnicodeError) as exc:
            raise MarkerError("In-place restore authority record is unreadable.") from exc
        if not isinstance(record, dict) or set(record) != {
            "version", "binding", "previous_marker", "capture_provenance"
        } or record["version"] != 1 or record["binding"]["operation"] != asdict(operation):
            raise MarkerError("In-place restore authority record does not match the operation.")
        previous = parse_marker(record["previous_marker"])
        if previous.state not in {MarkerState.NORMAL, MarkerState.ACKNOWLEDGED_NORMAL} or previous.operation is not None:
            raise MarkerError("In-place restore previous marker is invalid.")
        return record, previous

    def begin(self, operation, live_database, configuration_sha256, topology_sha256, capture_provenance):
        """Record OLD marker and planned NEW config before narrowing launch authority."""
        self._locked(operation)
        current = self._marker()
        if current.state not in {MarkerState.NORMAL, MarkerState.ACKNOWLEDGED_NORMAL} or current.operation is not None:
            raise MarkerError("In-place restore requires a normal, unclaimed target marker.")
        self._live(live_database, current.require_bound_database())
        if capture_provenance not in {"signed-full", "local-legacy-operation"} or self.record_path.exists():
            raise MarkerError("In-place restore requires a new private operation record.")
        previous = marker_payload(current.state, current.database, readiness={
            "reservations": list(current.reservations), "fences": list(current.fences),
            "not_restored": list(current.not_restored),
        })
        binding = phase_binding(operation, configuration_sha256, topology_sha256)
        record = {"version": 1, "binding": binding, "previous_marker": previous,
                  "capture_provenance": capture_provenance}
        write_private_file_fsynced(
            self.record_path, json.dumps(record, sort_keys=True) + "\n",
            require_root_owned=self.require_root_owned,
        )
        begun = self.ledger.begin("inplace-marker-block", {"binding": binding})
        self.transition._replace(marker_payload(
            MarkerState.RESTORE_BLOCKED, live_database, operation=operation,
            readiness=previous["readiness"],
        ))
        self.ledger.finish(begun)
        return record

    def _success(self, operation, live_database, configuration_sha256, topology_sha256, *, allow_released=False):
        record, previous = self._read_record(operation)
        self._live(live_database, previous.require_bound_database())
        current = self._marker()
        if (current.require_bound_database() != live_database
                or (current.operation != operation and not (allow_released and current.operation is None))):
            raise MarkerError("In-place restore marker operation or target changed.")
        binding = phase_binding(operation, configuration_sha256, topology_sha256)
        if record["binding"] != binding:
            raise MarkerError("In-place restore installed configuration differs from the admitted plan.")
        records = self.ledger.records()
        blocked = [item for item in records if item["phase"] == "inplace-marker-block" and item["state"] == "done"]
        if len(blocked) != 1 or blocked[0]["detail"] != {"binding": binding}:
            raise MarkerError("In-place restore lacks its durable blocked-marker phase.")
        last_index = records.index(blocked[0])
        for phase in VERIFIED_PHASES:
            done = [item for item in records if item["phase"] == phase and item["state"] == "done"]
            if len(done) != 1 or set(done[0]["detail"]) != {"binding", "evidence_sha256"}:
                raise MarkerError("In-place restore lacks a completed root verification phase.")
            if done[0]["detail"]["binding"] != binding:
                raise MarkerError("In-place restore verification phase binds different configuration.")
            _digest(done[0]["detail"]["evidence_sha256"])
            started = [item for item in records if item["phase"] == phase and item["state"] == "begun"]
            if len(started) != 1 or records.index(started[0]) <= last_index:
                raise MarkerError("In-place restore verification phases are out of order.")
            last_index = records.index(done[0])
        return current, previous, binding

    def complete(self, operation, live_database, proof, *, configuration_sha256, topology_sha256):
        current, previous, binding = self._success(operation, live_database, configuration_sha256, topology_sha256)
        if current.state != MarkerState.RESTORE_BLOCKED:
            raise MarkerError("In-place restore success requires the blocked marker.")
        outcome = validate_recovery_proof(proof, operation.restore_id, acknowledgement=False)
        state = MarkerState.QUARANTINED_AFTER_CUTOVER if outcome == "quarantined" else previous.state
        begun = self.ledger.begin("inplace-terminal", {"binding": binding, "outcome": outcome})
        self.ledger.finish(begun)
        return self.transition._replace(marker_payload(
            state, live_database, operation=operation if outcome == "quarantined" else None,
            readiness={"reservations": list(previous.reservations), "fences": list(previous.fences),
                       "not_restored": list(previous.not_restored)},
        ))

    def block_failed_start(self, operation, live_database, *, configuration_sha256, topology_sha256):
        """Narrow admission again when verified terminal rollout fails; never release."""
        current, previous, binding = self._success(
            operation, live_database, configuration_sha256, topology_sha256,
            allow_released=True,
        )
        records = self.ledger.records()
        terminal = [item for item in records if item["phase"] == "inplace-terminal" and item["state"] == "done"]
        if (len(terminal) != 1 or terminal[0]["detail"].get("binding") != binding
                or terminal[0]["detail"].get("outcome") not in {"normal", "quarantined"}):
            raise MarkerError("Failed rollout has no exact completed terminal verification.")
        outcome = terminal[0]["detail"]["outcome"]
        normal = (outcome == "normal" and current.state == previous.state and current.operation is None)
        quarantined = (outcome == "quarantined" and current.state == MarkerState.QUARANTINED_AFTER_CUTOVER
                       and current.operation == operation)
        acknowledged = False
        if outcome == "quarantined" and current.state == MarkerState.ACKNOWLEDGED_NORMAL and current.operation is None:
            acknowledgements = [item for item in records if item["phase"] == "inplace-host-ack" and item["state"] == "done"]
            acknowledged = len(acknowledgements) == 1 and acknowledgements[0]["detail"] == {"binding": binding}
        if not (normal or quarantined or acknowledged):
            raise MarkerError("Failed rollout marker is outside the exact completed restore lifecycle.")
        begun = self.ledger.begin("inplace-launch-failed", {"binding": binding})
        payload = self.transition._replace(marker_payload(
            MarkerState.RESTORE_BLOCKED, live_database, operation=operation,
            readiness={"reservations": list(previous.reservations), "fences": list(previous.fences),
                       "not_restored": list(previous.not_restored)},
        ))
        self.ledger.finish(begun)
        return payload

    def acknowledge(self, operation, live_database, proof, *, configuration_sha256, topology_sha256):
        current, previous, binding = self._success(operation, live_database, configuration_sha256, topology_sha256)
        if current.state != MarkerState.QUARANTINED_AFTER_CUTOVER:
            raise MarkerError("Host acknowledgement requires the quarantined marker.")
        validate_recovery_proof(proof, operation.restore_id, acknowledgement=True)
        terminal = [item for item in self.ledger.records() if item["phase"] == "inplace-terminal" and item["state"] == "done"]
        if len(terminal) != 1 or terminal[0]["detail"] != {"binding": binding, "outcome": "quarantined"}:
            raise MarkerError("Host acknowledgement lacks successful terminal root verification.")
        begun = self.ledger.begin("inplace-host-ack", {"binding": binding})
        self.ledger.finish(begun)
        return self.transition._replace(marker_payload(
            MarkerState.ACKNOWLEDGED_NORMAL, live_database,
            readiness={"reservations": list(previous.reservations), "fences": list(previous.fences),
                       "not_restored": list(previous.not_restored)},
        ))
