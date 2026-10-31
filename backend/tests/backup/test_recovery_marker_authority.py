"""Real root marker, pointer, flock and append-only run ledger transitions."""

from dataclasses import replace
import os

import pytest

from apps.backup.host_marker import MarkerError, MarkerState, marker_payload, parse_marker, read_marker
from apps.backup.host_pointer import PointerRecord, write_pointer_atomic
from apps.backup.inplace_marker import VERIFIED_PHASES, phase_binding
from apps.backup.process_roles import ProcessRole, admission_for
from tests.backup.recovery_test_support import CONFIG, TOPOLOGY, marker_rig, recovery_proof


def test_shared_0666_lock_permits_block_then_backend_only_quarantine_and_ack(tmp_path):
    with marker_rig(tmp_path) as rig:
        rig.begin()
        marker = read_marker(rig.marker)
        assert marker.state == MarkerState.RESTORE_BLOCKED
        assert marker.database == rig.identity and marker.operation == rig.operation
        assert {role for role in ProcessRole if admission_for(marker.state, role).admitted} == {ProcessRole.MANAGEMENT}
        rig.phases()
        rig.complete()
        assert read_marker(rig.marker).state == MarkerState.QUARANTINED_AFTER_CUTOVER
        assert {role for role in ProcessRole if admission_for(MarkerState.QUARANTINED_AFTER_CUTOVER, role).admitted} == {ProcessRole.BACKEND}
        rig.controller.acknowledge(rig.operation, rig.identity, recovery_proof(acknowledged=True),
            configuration_sha256=CONFIG, topology_sha256=TOPOLOGY)
        assert read_marker(rig.marker).state == MarkerState.ACKNOWLEDGED_NORMAL
        assert read_marker(rig.marker).operation is None
        assert all(admission_for(MarkerState.ACKNOWLEDGED_NORMAL, role).admitted for role in ProcessRole)


@pytest.mark.parametrize("fault", ["missing-phase", "order", "config", "target", "operation", "pointer", "unfinished"])
def test_incomplete_or_misbound_root_proof_never_releases_writers(tmp_path, fault):
    with marker_rig(tmp_path) as rig:
        rig.begin()
        phases = VERIFIED_PHASES[:-1] if fault in {"missing-phase", "unfinished"} else VERIFIED_PHASES
        if fault == "order":
            phases = tuple(reversed(phases))
        binding = phase_binding(rig.operation, "e" * 64, TOPOLOGY) if fault == "config" else None
        rig.phases(phases, binding=binding)
        if fault == "unfinished":
            rig.ledger.begin(VERIFIED_PHASES[-1], {"binding": phase_binding(rig.operation, CONFIG, TOPOLOGY)})
        if fault == "pointer":
            write_pointer_atomic(rig.pointer, PointerRecord("postgres://app:secret@db:5432/recovery_target", 8),
                expected_generation=7, invalidate=lambda _reason: None)
        operation = replace(rig.operation, artifact_sha256="f" * 64) if fault == "operation" else rig.operation
        identity = replace(rig.identity, oid=16385) if fault == "target" else rig.identity
        with pytest.raises(MarkerError):
            rig.controller.complete(operation, identity, recovery_proof(),
                configuration_sha256=CONFIG, topology_sha256=TOPOLOGY)
        assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED


@pytest.mark.parametrize("mutation", ["missing-op", "intent", "missing-db"])
def test_blocked_marker_cannot_be_unbound_or_anonymous(tmp_path, mutation):
    with marker_rig(tmp_path) as rig:
        payload = marker_payload(MarkerState.RESTORE_BLOCKED, rig.identity, operation=rig.operation)
        if mutation == "missing-op":
            payload.pop("operation")
        elif mutation == "intent":
            payload["database"] = {"binding": "intent"}
        else:
            payload.pop("database")
        with pytest.raises(MarkerError):
            parse_marker(payload)


@pytest.mark.parametrize("fault", ["active", "stage", "principal", "text", "naive-time"])
def test_acknowledgement_requires_exact_fresh_recovered_principal_facts(tmp_path, fault):
    with marker_rig(tmp_path) as rig:
        rig.begin()
        rig.phases()
        rig.complete()
        proof = recovery_proof(acknowledged=True)
        key, value = {"active": ("active_restore", None), "stage": ("stage", "failed"),
            "principal": ("acknowledged_by", 43), "text": ("acknowledgement", "yes"),
            "naive-time": ("acknowledged_at", "2026-10-30T12:00:00")}[fault]
        proof[key] = value
        with pytest.raises(MarkerError):
            rig.controller.acknowledge(rig.operation, rig.identity, proof,
                configuration_sha256=CONFIG, topology_sha256=TOPOLOGY)
        assert read_marker(rig.marker).state == MarkerState.QUARANTINED_AFTER_CUTOVER


@pytest.mark.parametrize("normal", [False, True])
def test_terminal_launch_failure_reblocks_exact_operation_and_retains_history(tmp_path, normal):
    with marker_rig(tmp_path) as rig:
        rig.begin()
        rig.phases()
        rig.complete(recovery_proof(normal=normal))
        before = rig.ledger.path.read_bytes()
        rig.controller.block_failed_start(rig.operation, rig.identity,
            configuration_sha256=CONFIG, topology_sha256=TOPOLOGY)
        marker = read_marker(rig.marker)
        assert marker.state == MarkerState.RESTORE_BLOCKED and marker.operation == rig.operation
        assert rig.ledger.path.read_bytes().startswith(before)
        assert rig.ledger.records()[-1]["phase"] == "inplace-launch-failed"


@pytest.mark.parametrize("fault", ["hardlink", "symlink", "replacement", "foreign-owner"])
def test_actual_lock_inode_trust_is_checked_again_at_marker_transition(tmp_path, fault):
    with marker_rig(tmp_path) as rig:
        lock = rig.ops / "operation.lock"
        if fault == "hardlink":
            os.link(lock, rig.ops / "alias")
        elif fault == "symlink":
            lock.rename(rig.ops / "held")
            lock.symlink_to(rig.ops / "held")
        elif fault == "replacement":
            lock.rename(rig.ops / "held")
            lock.touch(mode=0o666)
        else:
            os.chown(lock, 65534, 65534)
        with pytest.raises(MarkerError):
            rig.begin()
        assert read_marker(rig.marker).state == MarkerState.NORMAL
        assert not rig.ledger.path.exists()
