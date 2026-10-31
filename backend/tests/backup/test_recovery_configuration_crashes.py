"""Actual fsynced env/topology writes with faults around replacement boundaries."""

import json

import pytest

from apps.backup.host_marker import MarkerState, read_marker
from apps.backup.host_restore_configuration import ConfigurationTransition, verify_installed_configuration
from apps.backup.host_restore_transport import RestoreHostError
from apps.backup.host_topology_record import TopologyRecordError
from tests.backup.recovery_test_support import marker_rig
from tests.backup.test_recovery_lifecycle_synthetic import operation


@pytest.mark.parametrize("boundary", ["before-env", "after-env", "before-record", "after-record"])
def test_each_interrupted_configuration_pair_remains_blocked_without_key_reversal(tmp_path, monkeypatch, boundary):
    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        from apps.backup import host_restore_files as files, host_restore_configuration as config

        env_write, record_write = files.install_environment, config.write_topology_record
        def environment(path, contents):
            assert not op.t.running & {"backend", "worker", "beat"}
            assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED
            assert json.loads((op.i.private / "configuration.json").read_bytes())["phase"] == "replacing-environment"
            if boundary == "before-env":
                raise OSError("synthetic interrupted rename")
            env_write(path, contents)
            if boundary == "after-env":
                raise OSError("synthetic interrupted fsync")
        def record(path, facts):
            assert op.t.static_env.read_bytes() == (op.i.private / "environment.new").read_bytes()
            if boundary == "before-record":
                raise OSError("synthetic interrupted topology rename")
            record_write(path, facts)
            if boundary == "after-record":
                raise OSError("synthetic interrupted record fsync")
        monkeypatch.setattr(files, "install_environment", environment)
        monkeypatch.setattr(config, "write_topology_record", record)
        with pytest.raises(OSError, match="synthetic interrupted"):
            op.restore("proceed")
        current = op.t.static_env.read_bytes()
        op.retain_failure()
        assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED
        assert op.t.static_env.read_bytes() == current
        assert "sql-restore" not in op.t.events
        assert not op.t.running & {"backend", "worker", "beat"}
        assert (op.i.private / "environment.old").read_bytes() == op.old_environment
        with pytest.raises(RestoreHostError, match="manual recovery"):
            ConfigurationTransition(op.t, op.i.private)
        with pytest.raises(RestoreHostError, match="completed NEW"):
            verify_installed_configuration(op.t, op.i.private)
        if boundary in {"after-env", "before-record"}:
            with pytest.raises(TopologyRecordError, match="drifted"):
                op.t.validate()


def test_unrecorded_env_or_compose_drift_is_never_blessed(tmp_path):
    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        op.t.static_env.write_bytes(op.old_environment + b"ARBITRARY=1\n")
        with pytest.raises(TopologyRecordError, match="drifted"):
            op.t.validate()
        op.t.static_env.write_bytes(op.old_environment)
        op.t.files[0].write_bytes(b"unreviewed topology\n")
        with pytest.raises(TopologyRecordError, match="drifted"):
            op.t.validate()
