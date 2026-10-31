"""Actual lifecycle/marker/configuration; Docker, SQL and providers are synthetic.

These are failure-order tests, not production host or database restore evidence.
"""

import pytest

from apps.backup.host_marker import MarkerState, read_marker
from apps.backup.host_restore_configuration import verify_installed_configuration
from apps.backup.host_restore_lifecycle import InplaceRestore
from apps.backup.host_restore_transport import RestoreHostError
from apps.backup.host_topology_record import TopologyRecordError
from tests.backup.recovery_test_support import marker_rig
from tests.backup.recovery_transport_support import SyntheticTransport, lifecycle_inputs


def operation(rig, tmp_path):
    t = SyntheticTransport(rig, tmp_path)
    inputs = lifecycle_inputs(tmp_path)
    inputs.preflight = lambda *a, **kw: t.hit("installed-preflight" if not kw.get("prospective") else "prospective-preflight")
    inputs.export_control = lambda _decision: t.hit("export-control")
    op = InplaceRestore(t, rig.lock, inputs, rig.identity)
    # Execute actual decision/quiescence/dump/diff ordering. The wire returns a
    # synthetic operator decision and synthetic SQL bytes, never a real diff claim.
    assert op.decision() == "proceed"
    return op


@pytest.mark.parametrize("failure", ["stop:backend,worker,beat", "installed-preflight", "control:stage",
    "sql-restore", "grants", "control:rehydrate", "control:verify-source-objects",
    "control:restore-objects", "control:verify-restored-objects", "control:validate",
    "control:quarantine", "start:backend"])
def test_each_post_block_failure_retains_private_copies_current_env_and_stops_writers(tmp_path, failure):
    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        op.t.failure = failure
        with pytest.raises(RestoreHostError, match="synthetic transport failure"):
            op.restore("proceed")
        current_environment = op.t.static_env.read_bytes()
        # Injected fault is one operation failure, not a permanently dead daemon.
        op.t.failure = None
        op.retain_failure()
        marker = read_marker(rig.marker)
        assert marker.state == MarkerState.RESTORE_BLOCKED and marker.operation == op.operation
        assert not op.t.running & {"backend", "worker", "beat"}
        assert op.t.static_env.read_bytes() == current_environment
        assert (op.i.private / "environment-before.env").read_bytes() == op.old_environment
        assert (op.i.private / "environment.old").read_bytes() == op.old_environment
        assert (op.i.private / "environment.new").is_file()
        assert (op.i.private / "pre-restore.dump").read_bytes() == b"synthetic SQL rollback copy"
        assert (op.i.private / "bundle/database.dump").read_bytes() == b"synthetic source dump"
        assert (op.i.private / "failure.json").is_file()
        assert not any(event == "control:fail" for event in op.t.events)
        assert not any(isinstance(event, str) and event.startswith("start:worker") for event in op.t.events)
        if "sql-restore" in op.t.events:
            assert current_environment != op.old_environment


def test_success_stops_old_writers_before_env_then_static_checks_before_sql_and_source_closure_before_copies(tmp_path):
    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        op.restore("proceed")
        events = op.t.events
        assert events.index("stop:backend,worker,beat") < events.index("installed-preflight") < events.index("sql-restore")
        grants = max(index for index, event in enumerate(events) if event == "grants")
        assert events.index("sql-restore") < grants < events.index("control:rehydrate") < events.index("control:verify-source-objects")
        assert events.index("control:verify-source-objects") < events.index("control:restore-objects") < events.index("control:verify-restored-objects")
        assert read_marker(rig.marker).state == MarkerState.QUARANTINED_AFTER_CUTOVER
        assert op.t.running & {"backend", "worker", "beat"} == {"backend"}
        assert "start:worker,beat" not in events
        verify_installed_configuration(op.t, op.i.private)


def test_cancel_at_sql_is_retained_like_other_post_effect_failure(tmp_path):
    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        original_sql = op.t.sql
        def cancel(command, **kwargs):
            if command.startswith("pg_restore"):
                raise KeyboardInterrupt
            return original_sql(command, **kwargs)
        op.t.sql = cancel
        with pytest.raises(KeyboardInterrupt):
            op.restore("proceed")
        before = op.t.static_env.read_bytes()
        op.retain_failure()
        assert op.t.static_env.read_bytes() == before != op.old_environment
        assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED
        assert not op.t.running & {"backend", "worker", "beat"}


@pytest.mark.parametrize("fault", [None, "environment", "marker", "proof"])
def test_explicit_preeffect_abort_restarts_writers_only_with_exact_old_state(tmp_path, fault):
    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        original_probe = op.t.probe
        def abort_probe():
            result = original_probe()
            result["recovery_proof"].update(mode="normal", active_restore=None, stage="aborted", decision="abort")
            if fault == "proof":
                result["recovery_proof"]["active_restore"] = op.id
            return result
        op.t.probe = abort_probe
        if fault == "environment":
            op.t.static_env.write_bytes(op.old_environment + b"CHANGED=1\n")
        if fault == "marker":
            from apps.backup.host_marker import marker_payload, write_marker_fsynced
            write_marker_fsynced(rig.marker, marker_payload(MarkerState.ACKNOWLEDGED_NORMAL, rig.identity))
        if fault:
            with pytest.raises((RestoreHostError, TopologyRecordError)):
                op.finish_abort()
            assert "start:worker,beat" not in op.t.events
        else:
            op.finish_abort()
            assert "start:worker,beat" in op.t.events
            assert (op.i.private / "abort-verified.json").is_file()


@pytest.mark.parametrize("fault", ["journal-seal", "sql-ledger", "block-marker-fsync", "terminal-marker-fsync"])
def test_private_journal_ledger_or_marker_write_interruption_never_releases_writers(tmp_path, monkeypatch, fault):
    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        if fault == "journal-seal":
            from apps.backup import host_restore_lifecycle as lifecycle
            original = lifecycle.seal_file
            def seal(source, target, **kwargs):
                if source.name == "swap-journal.jsonl":
                    raise OSError("synthetic journal fsync interruption")
                return original(source, target, **kwargs)
            monkeypatch.setattr(lifecycle, "seal_file", seal)
        elif fault == "sql-ledger":
            original = op.ledger.finish
            def finish(begun, detail=None):
                if begun["phase"] == "inplace-sql-restored":
                    raise OSError("synthetic root ledger interruption")
                return original(begun, detail)
            monkeypatch.setattr(op.ledger, "finish", finish)
        else:
            def interrupted(stage):
                state = read_marker(rig.marker).state if rig.marker.exists() else None
                wanted = MarkerState.RESTORE_BLOCKED if fault == "block-marker-fsync" else MarkerState.QUARANTINED_AFTER_CUTOVER
                if stage == "after_replace" and state == wanted:
                    raise OSError("synthetic marker directory fsync interruption")
            op.marker.transition.crash_hook = interrupted
        with pytest.raises(OSError, match="synthetic"):
            op.restore("proceed")
        current = op.t.static_env.read_bytes()
        # The injected one-shot interruption is resolved; retained evidence is not.
        op.marker.transition.crash_hook = None
        op.retain_failure()
        assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED
        assert op.t.static_env.read_bytes() == current
        assert not op.t.running & {"backend", "worker", "beat"}
        assert (op.i.private / "pre-restore.dump").is_file()
        assert (op.i.private / "bundle/database.dump").is_file()
