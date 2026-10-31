"""Actual controller lock scope with synthetic boundary responses; no host attestation."""

import os
import runpy
import subprocess
import sys
from types import SimpleNamespace

import pytest

from apps.backup.host_restore_transport import RestoreTransport
from apps.backup.operation_lock import host_operation_lock
from tests.backup.recovery_test_support import RESTORE_ID, marker_rig, repo_root, require_linux_root


CONTEND = """
import fcntl,sys
with open(sys.argv[1], 'a+') as h:
    try: fcntl.flock(h, fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: sys.exit(73)
sys.exit(0)
"""


def contention(path):
    return subprocess.run([sys.executable, "-I", "-B", "-c", CONTEND, str(path)],
        close_fds=True, capture_output=True, timeout=10).returncode


@pytest.mark.parametrize("command", ["restore", "import", "resume-host", "recover-superadmin"])
def test_main_keeps_one_real_lock_across_admission_import_and_terminal(monkeypatch, tmp_path, command):
    require_linux_root()
    # The rig prepares genuine root/pointer/marker authority; release its setup lock
    # before the controller acquires the same inode itself.
    with marker_rig(tmp_path) as rig:
        ops, marker = rig.ops, rig.marker
    transport = SimpleNamespace(ops=ops, host=marker.parents[1])
    namespace = runpy.run_path(str(repo_root() / "scripts/restore-host.py"))
    scope = namespace["main"].__globals__
    calls = []

    def held(name, result=None):
        assert contention(ops / "operation.lock") == 73, name
        calls.append(name)
        return result

    scope["RestoreTransport"] = lambda _root: transport
    scope["admit_configuration"] = lambda _t: held("admit")
    scope["inventory"] = lambda _t: held("inventory")
    scope["target_identity"] = lambda _t: held("identity", rig.identity)
    scope["fixed_probe"] = lambda _t: held("probe", {"recovery_state": {"mode": "normal", "active_restore": None}})
    scope["RestoreInputs"] = lambda *a, **k: held("inputs", object())

    class Operation:
        def __init__(self, *_args):
            held("operation")
        def decision(self):
            return held("decision", "proceed")
        def restore(self, _decision):
            held("terminal")

    scope["InplaceRestore"] = Operation
    scope["resume_host"] = lambda *_args: held("resume")
    scope["recover_principal"] = lambda *_args: held("recover")
    argv = {"restore": [command, RESTORE_ID], "import": [command, "/input.age", "operator"],
        "resume-host": [command, RESTORE_ID], "recover-superadmin": [command, RESTORE_ID, "operator"]}[command]
    monkeypatch.setattr(sys, "argv", ["restore-host.py", *argv])
    old_handlers = {sig: __import__("signal").getsignal(sig) for sig in (1, 15)}
    try:
        namespace["main"]()
    finally:
        for sig, handler in old_handlers.items():
            __import__("signal").signal(sig, handler)
    assert calls[-1] == {"restore": "terminal", "import": "terminal", "resume-host": "resume", "recover-superadmin": "recover"}[command]
    assert contention(ops / "operation.lock") == 0
    assert "cleanup_rollback" not in calls  # Existing negative dispatch guard remains untouched.


def test_real_transport_closes_even_explicitly_inheritable_child_fds(tmp_path):
    require_linux_root()
    t = object.__new__(RestoreTransport)
    t.root, t.environment = tmp_path, {"PATH": os.environ["PATH"]}
    with host_operation_lock(tmp_path) as lock, (tmp_path / "other").open("w") as other:
        os.set_inheritable(lock.fileno(), True)
        os.set_inheritable(other.fileno(), True)
        identities = [(os.fstat(h.fileno()).st_dev, os.fstat(h.fileno()).st_ino) for h in (lock, other)]
        code = """import json,os
seen=[]
for fd in os.listdir('/proc/self/fd'):
    try: s=os.fstat(int(fd)); seen.append([s.st_dev,s.st_ino])
    except OSError: pass
print(json.dumps(seen))
"""
        seen = t.execute([sys.executable, "-I", "-B", "-c", code], json_result=True)
        assert not set(map(tuple, seen)) & set(identities)
        assert contention(tmp_path / "operation.lock") == 73


def test_actual_nobody_child_cannot_claim_root_operation_lock(tmp_path):
    require_linux_root()
    # /tmp ancestor is traversable; no mocked geteuid or ownership.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="recovery-nonroot-", dir="/tmp") as directory:
        path = Path(directory)
        path.chmod(0o755)
        (path / "operation.lock").touch(mode=0o666)
        (path / "operation.lock").chmod(0o666)
        code = """import sys
sys.path.insert(0,sys.argv[1])
from apps.backup.operation_lock import host_operation_lock,OperationLockUnavailable
try:
    with host_operation_lock(sys.argv[2], require_root_owned=True): pass
except OperationLockUnavailable: sys.exit(73)
sys.exit(0)
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(repo_root() / "backend"), str(path)],
            user=65534, group=65534, extra_groups=[], capture_output=True, timeout=10)
        assert result.returncode == 73, result.stderr


def test_controller_compound_protection_refuses_before_any_admission_or_input_effect(tmp_path, monkeypatch):
    from apps.backup.host_marker import MarkerState, marker_payload, write_marker_fsynced
    from apps.backup.host_restore_transport import RestoreHostError
    with marker_rig(tmp_path) as rig:
        pass
    readiness = {"reservations": [{"schema": "public", "table": "protected", "expected_rows": 0, "sha256": "a" * 64}],
        "fences": [], "not_restored": []}
    write_marker_fsynced(rig.marker, marker_payload(MarkerState.NORMAL, rig.identity, readiness=readiness))
    namespace = runpy.run_path(str(repo_root() / "scripts/restore-host.py"))
    scope = namespace["main"].__globals__
    scope["RestoreTransport"] = lambda _root: SimpleNamespace(ops=rig.ops, host=rig.marker.parents[1])
    def forbidden(*args, **kwargs):
        raise AssertionError("Compound protection must refuse before admission, inputs or SQL")
    scope["admit_configuration"] = forbidden
    scope["RestoreInputs"] = forbidden
    monkeypatch.setattr(sys, "argv", ["restore-host.py", "restore", RESTORE_ID])
    old_handlers = {sig: __import__("signal").getsignal(sig) for sig in (1, 15)}
    try:
        with pytest.raises(RestoreHostError, match="Protected compound target"):
            namespace["main"]()
    finally:
        for sig, handler in old_handlers.items():
            __import__("signal").signal(sig, handler)
    assert contention(rig.ops / "operation.lock") == 0
