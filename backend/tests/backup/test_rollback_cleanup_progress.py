"""Cursor trust, real process sharing, and truthful late persistence failures."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from apps.backup import host_private_file, rollback_cleanup
from apps.backup import rollback_cleanup_progress as progress
from apps.backup.operation_lock import deployment_operation_lock
from tests.backup.rollback_cleanup_outcome_helpers import assert_retained, case, snapshot
from tests.backup.rollback_cleanup_progress_helpers import (
    assert_cleaned, cleanup_env, module_store, outcome_store, progress_boundary,
    save_cursor, saved_cursor,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("raw", [
    pytest.param(b"\xff", id="corrupt-utf8"),
    pytest.param(b'{"version":1,"last_id":}', id="malformed-json"),
    pytest.param(b'{"version":1,"last_id":0,"extra":0}', id="extra-field"),
    pytest.param(b'{"version":1,"last_id":0,"last_id":1}', id="duplicate-field"),
    pytest.param(b'{"version":true,"last_id":0}', id="boolean-version"),
    pytest.param(b'{"version":1,"last_id":false}', id="boolean-last-id"),
    pytest.param(b'{"version":1,"last_id":-1}', id="negative-last-id"),
    pytest.param(b'{"version":1,"last_id":0}'.ljust(257, b" "), id="over-256-bytes"),
])
def test_invalid_private_cursor_refuses_before_transport_or_quota(raw, cleanup_env, outcome_store):
    item = case(outcome_store)
    cleanup_env.write_bytes(raw)
    cleanup_env.chmod(0o600)
    before = snapshot(item, outcome_store)
    with pytest.raises(progress.RollbackCleanupProgressUnavailable):
        rollback_cleanup.cleanup_expired_rollback_objects(limit=1)
    assert_retained(item, outcome_store, before)
    assert cleanup_env.read_bytes() == raw


@pytest.mark.parametrize("fault", ["final-symlink", "hardlink", "group-readable", "parent-mode"])
def test_untrusted_cursor_inode_or_parent_refuses_before_transport(fault, cleanup_env, outcome_store):
    item = case(outcome_store)
    target = cleanup_env.with_name("private-target.json")
    target.write_text('{"version":1,"last_id":0}', encoding="utf-8")
    target.chmod(0o600)
    if fault == "final-symlink":
        cleanup_env.symlink_to(target)
    elif fault == "hardlink":
        os.link(target, cleanup_env)
    else:
        cleanup_env.write_bytes(target.read_bytes())
        cleanup_env.chmod(0o640 if fault == "group-readable" else 0o600)
        if fault == "parent-mode":
            cleanup_env.parent.chmod(0o750)
    before = snapshot(item, outcome_store)
    with pytest.raises(progress.RollbackCleanupProgressUnavailable):
        rollback_cleanup.cleanup_expired_rollback_objects(limit=1)
    assert_retained(item, outcome_store, before)


# Configure only the filesystem setting: no Django app setup, DB, or inherited secrets.
CHILD_PROGRESS = """
import json, sys
from django.conf import settings
settings.configure(BACKUP_OPS_DIR=sys.argv[1])
from apps.backup.operation_lock import deployment_operation_lock, OperationLockUnavailable
from apps.backup.rollback_cleanup_progress import read_cleanup_progress, write_cleanup_progress
assert 'django.db' not in sys.modules
try:
    with deployment_operation_lock(blocking=False):
        before = read_cleanup_progress()
        if sys.argv[2] == 'write':
            write_cleanup_progress(before, int(sys.argv[3]))
        print(json.dumps({'before': before.last_id, 'after': read_cleanup_progress().last_id}))
except OperationLockUnavailable:
    print(json.dumps({'busy': True}))
assert 'django.db' not in sys.modules
"""


@pytest.mark.parametrize("layout", ["work", "direct-ops"])
def test_progress_is_shared_with_a_second_process_under_real_host_lock(layout, tmp_path, settings):
    ops = tmp_path / "shared-ops"
    directory = ops / "work" if layout == "work" else ops
    directory.mkdir(parents=True, mode=0o700)
    settings.BACKUP_OPS_DIR = str(directory)

    def child(action, last_id=0):
        result = subprocess.run(
            [sys.executable, "-c", CHILD_PROGRESS, str(directory), action, str(last_id)],
            cwd=Path(__file__).resolve().parents[2], env={"PATH": os.defpath},
            capture_output=True, text=True, timeout=15, check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    save_cursor(7)
    with progress_boundary():
        assert child("write", 11) == {"busy": True}
        assert progress.read_cleanup_progress().last_id == 7
    assert child("write", 11) == {"before": 7, "after": 11}
    assert saved_cursor() == 11
    save_cursor(13)
    assert child("read") == {"before": 13, "after": 13}
    assert stat.S_IMODE((directory / progress.CURSOR_NAME).stat().st_mode) == 0o600


def test_busy_host_returns_before_reading_a_corrupt_cursor(cleanup_env, outcome_store):
    item = case(outcome_store)
    cleanup_env.write_bytes(b"corrupt cursor would refuse if read")
    cleanup_env.chmod(0o600)
    before = snapshot(item, outcome_store)
    with deployment_operation_lock(blocking=False):
        assert rollback_cleanup.cleanup_expired_rollback_objects(limit=1) == {
            "status": "busy", "cleaned": 0, "skipped": 0,
        }
    assert_retained(item, outcome_store, before)
    assert cleanup_env.read_bytes() == b"corrupt cursor would refuse if read"


@pytest.mark.parametrize("phase", ["write", "file-fsync", "replace", "directory-fsync"])
def test_late_cursor_fault_reports_actual_cleanup_and_retry_never_credits_twice(
    phase, cleanup_env, outcome_store, monkeypatch, caplog,
):
    item = case(outcome_store)
    save_cursor(0)
    hits = []

    def fail():
        # The failure is reached only after provider deletion AND SQL settlement.
        assert_cleaned(item, outcome_store)
        hits.append(phase)
        raise OSError(f"injected {phase} failure")

    real_fdopen, real_fsync, real_replace = os.fdopen, os.fsync, os.replace

    class FaultingWriter:
        def write(self, _data):
            fail()

        def __getattr__(self, name):
            return getattr(self.handle, name)

    @contextmanager
    def faulting_fdopen(fd, mode, *args, **kwargs):
        with real_fdopen(fd, mode, *args, **kwargs) as handle:
            wrapper = FaultingWriter()
            wrapper.handle = handle
            yield wrapper

    def fdopen(fd, mode="r", *args, **kwargs):
        # os is shared with the real host lock, whose a+ handle is not used as
        # a context manager. Inject only at the cursor writer's wb boundary.
        if mode == "wb":
            return faulting_fdopen(fd, mode, *args, **kwargs)
        return real_fdopen(fd, mode, *args, **kwargs)

    def fsync(fd):
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if is_directory == (phase == "directory-fsync"):
            fail()
        return real_fsync(fd)

    def replace(source, target, *args, **kwargs):
        if Path(target) == cleanup_env:
            fail()
        return real_replace(source, target, *args, **kwargs)

    with monkeypatch.context() as patch:
        if phase == "write":
            patch.setattr(host_private_file.os, "fdopen", fdopen)
        elif phase == "replace":
            patch.setattr(host_private_file.os, "replace", replace)
        else:
            patch.setattr(host_private_file.os, "fsync", fsync)
        assert rollback_cleanup.cleanup_expired_rollback_objects(limit=1) == {
            "status": "retained", "cleaned": 1, "skipped": 0,
            "error_code": "rollback_cleanup_progress_unconfirmed",
        }
    assert hits == [phase]
    assert any(getattr(record, "error_code", None) == "rollback_cleanup_progress_unconfirmed"
               and record.cleaned == 1 for record in caplog.records)
    # A failed directory fsync can leave the replacement visible; no zero-effect claim.
    assert saved_cursor() in ({0, item.row.pk} if phase == "directory-fsync" else {0})
    calls = list(outcome_store.calls)
    assert rollback_cleanup.cleanup_expired_rollback_objects(limit=1) == {
        "status": "checked", "cleaned": 0, "skipped": 0,
    }
    assert_cleaned(item, outcome_store)
    assert outcome_store.calls == calls
    assert not list(cleanup_env.parent.glob(f".{progress.CURSOR_NAME}.*.tmp"))
