"""Real strict signature/settings admission in the actual lifecycle before SQL.

Docker/SQL transport and its one-shot environment projection are synthetic.
"""

import shutil

import pytest

from apps.backup.import_preflight import ImportPreflightError, validate_import_preflight
from apps.backup.host_marker import MarkerState, read_marker
from tests.backup.full_backup_fixture_helpers import OCI, make_full_fixture
from tests.backup.full_backup_preflight_helpers import configure_target
from tests.backup.recovery_test_support import marker_rig
from tests.backup.test_recovery_lifecycle_synthetic import operation


@pytest.mark.parametrize("wrong_installed_key", [False, True])
def test_new_installed_keys_must_pass_real_strict_preflight_before_sql(tmp_path, monkeypatch, wrong_installed_key):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    monkeypatch.setenv("SECRET_KEY", "OLD-target-key")
    monkeypatch.setattr("tests.backup.recovery_transport_support.DIGEST", OCI)
    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        op.i.manifest = fixture.manifest
        op.i.continuity = fixture.secrets
        op.i.prospective = "separately-authenticated-prospective-input"
        shutil.copytree(fixture.root, op.i.private / "bundle", dirs_exist_ok=True)
        def strict(_digest, **kwargs):
            assert not kwargs.get("prospective")
            assert not op.t.running & {"backend", "worker", "beat"}
            assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED
            assert b"fixture-continuity-SECRET_KEY" in op.t.static_env.read_bytes()
            op.t.hit("real-strict-preflight")
            # Model only the one-shot management process environment. No signature,
            # delegation, settings policy or target-compatibility check is replaced.
            with monkeypatch.context() as environment:
                for key, value in op.t.config["services"]["backend"]["environment"].items():
                    environment.setenv(key, value)
                if wrong_installed_key:
                    environment.setenv("SECRET_KEY", "WRONG-one-shot-key")
                validate_import_preflight(**fixture.kwargs(), require_host_support=True)
        op.i.preflight = strict
        if wrong_installed_key:
            with pytest.raises(ImportPreflightError, match="settings_policy"):
                op.restore("proceed")
            op.retain_failure()
            assert "sql-restore" not in op.t.events
            assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED
        else:
            op.restore("proceed")
            assert op.t.events.index("real-strict-preflight") < op.t.events.index("sql-restore")
            assert read_marker(rig.marker).state == MarkerState.QUARANTINED_AFTER_CUTOVER
