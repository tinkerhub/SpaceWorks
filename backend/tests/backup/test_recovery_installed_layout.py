"""Actual shell -> isolated Python on a genuinely copied 60-file Linux root layout.

Help/refusal prove packaging and parsing only, never a host restore.
"""

import importlib.util
import marshal
import os
from pathlib import Path
import struct

import pytest

from tests.backup.recovery_bundle_support import installed_root, inventory, run_wrapper, snapshot
from tests.backup.recovery_test_support import RESTORE_ID


def test_correct_copied_layout_help_and_missing_environment_have_no_effects():
    with installed_root() as root:
        assert len(snapshot(root)) == 60
        before = snapshot(root)
        help_result = run_wrapper(root, "--help")
        assert help_result.returncode == 0, help_result.stderr
        assert "restore_id" in help_result.stdout
        ordinary = run_wrapper(root, RESTORE_ID)
        assert ordinary.returncode != 0
        assert "No automatic rollback" in ordinary.stderr
        assert snapshot(root) == before
        assert not list(root.rglob("__pycache__"))
        assert not (root / "ops").exists()


def test_poisoned_valid_timestamp_bytecode_is_ignored_without_cache_writes():
    with installed_root() as root:
        source = root / "backend/apps/backup/host_restore_lifecycle.py"
        info = source.stat()
        cache = Path(importlib.util.cache_from_source(str(source)))
        cache.parent.mkdir(mode=0o755)
        code = compile("raise AssertionError('UNTRUSTED_BYTECODE_EXECUTED')", str(source), "exec")
        cache.write_bytes(importlib.util.MAGIC_NUMBER + struct.pack("<III", 0, int(info.st_mtime), info.st_size) + marshal.dumps(code))
        cache.chmod(0o644)
        before = snapshot(root)
        result = run_wrapper(root, "--help")
        assert result.returncode == 0, result.stderr
        assert "UNTRUSTED_BYTECODE_EXECUTED" not in result.stderr
        assert snapshot(root) == before
        assert len(list(root.rglob("*.pyc"))) == 1


@pytest.mark.parametrize("fault", ["missing", "altered", "symlink", "hardlink", "fifo", "owner", "writable"])
def test_each_guarded_dependency_refuses_before_controller_import(fault):
    guarded = [fact for fact in inventory() if fact["path"].startswith("backend/") or fact["path"] == "scripts/restore-host.py"]
    assert len(guarded) == 25
    for fact in guarded:
        with installed_root() as root:
            target = root / fact["path"]
            if fault == "altered":
                target.write_bytes(target.read_bytes() + b"\n# altered\n")
            elif fault == "owner":
                os.chown(target, 65534, 65534)
            elif fault == "writable":
                target.chmod(0o666)
            else:
                raw = target.read_bytes()
                target.unlink()
                if fault == "symlink":
                    other = root / "untrusted-target"
                    other.write_bytes(raw)
                    target.symlink_to(other)
                elif fault == "hardlink":
                    other = root / "untrusted-target"
                    other.write_bytes(raw)
                    os.link(other, target)
                elif fault == "fifo":
                    os.mkfifo(target, 0o644)
            result = run_wrapper(root, "--help")
            assert result.returncode != 0, (fault, fact["path"])
            assert "complete matching root-owned protected Linux host bundle" in result.stderr
            assert not list(root.rglob("__pycache__"))


def test_real_nobody_process_cannot_use_otherwise_correct_root_bundle():
    with installed_root() as root:
        result = run_wrapper(root, "--help", nonroot=True)
        assert result.returncode != 0
        assert "root-owned protected Linux host bundle" in result.stderr
        assert not list(root.rglob("__pycache__"))


def test_operator_owned_ancestor_refuses_even_when_invoked_by_root():
    with installed_root() as root:
        # This is an actual owner change to a disposable ancestor, not geteuid mocking.
        os.chown(root, 65534, 65534)
        result = run_wrapper(root, "--help")
        assert result.returncode != 0
        assert "root-owned protected Linux host bundle" in result.stderr


def test_linked_code_directory_refuses_before_python_import():
    with installed_root() as root:
        directory = root / "backend/apps/backup"
        relocated = root / "relocated-backup"
        directory.rename(relocated)
        directory.symlink_to(relocated, target_is_directory=True)
        result = run_wrapper(root, "--help")
        assert result.returncode != 0
        assert "root-owned protected Linux host bundle" in result.stderr
