"""Actual restore consumes the verified private copy for its full lifetime."""

import errno
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from apps.backup.operation_lock import OperationLockUnavailable, host_operation_lock
from apps.tenant_migration import tenant_restore_dump_snapshot as snapshots
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused
from tests.tenant_migration.x12_restore_test_helpers import RestoreScenario
from tests.tenant_migration.x12_selected_test_helpers import DUMP, SelectedArtifact, private_write


@pytest.mark.parametrize("outcome", ["success", "restore_error", "later_error"])
@pytest.mark.parametrize("original_change", ["none", "inplace", "replace"])
def test_restore_only_receives_live_private_snapshot_and_cleanup_holds_lock(
    tmp_path, monkeypatch, outcome, original_change,
):
    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    consumed = []
    original_offline = scenario.writers.persist_offline
    def offline(*args):
        if original_change == "inplace":
            artifact.dump_path.write_bytes(b"changed original after verified copy")
        elif original_change == "replace":
            artifact.dump_path.unlink()
            private_write(artifact.dump_path, b"replacement original")
        return original_offline(*args)
    scenario.writers.persist_offline = offline
    def restore(_sibling, path):
        path = Path(path)
        consumed.append(path)
        assert path != artifact.dump_path
        assert path.parent.parent == scenario.ops.resolve()
        assert path.read_bytes() == DUMP
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert path.stat().st_uid == os.geteuid()
        assert path.stat().st_nlink == 1
        assert artifact.reads.count("dump") == 1
        if outcome == "restore_error":
            raise RuntimeError("actual restore failed")
    scenario.database.restore = restore
    if outcome == "later_error":
        def fail(*_):
            assert consumed[0].exists()
            raise RuntimeError("later activation failed")
        scenario.target.verify_activation = fail
    cleanup = snapshots._DumpSnapshot.cleanup
    checked = []
    def locked_cleanup(snapshot):
        with pytest.raises(OperationLockUnavailable):
            with host_operation_lock(scenario.ops, require_root_owned=False):
                pass
        checked.append(snapshot.name)
        return cleanup(snapshot)
    monkeypatch.setattr(snapshots._DumpSnapshot, "cleanup", locked_cleanup)
    if outcome == "success":
        scenario.run()
    else:
        with pytest.raises(RuntimeError, match="restore failed|activation failed"):
            scenario.run()
    assert len(consumed) == len(checked) == 1
    assert not consumed[0].exists()
    assert not consumed[0].parent.exists()
    assert artifact.dump_path.exists()
    if original_change == "none":
        assert artifact.dump_path.read_bytes() == DUMP
    assert not list(scenario.ops.glob(".tenant-restore-dump-*"))
    ledger = scenario.ledger_path.read_text()
    assert str(consumed[0]) not in ledger
    assert "Source kiosk" not in ledger
    with host_operation_lock(scenario.ops, require_root_owned=False):
        pass


@pytest.mark.parametrize("case", ["wrong", "empty", "relative", "symlink", "hardlink", "fifo", "directory", "mode", "parent_mode", "owner"])
def test_bad_original_dump_refuses_before_first_phase(tmp_path, monkeypatch, case):
    artifact = SelectedArtifact(tmp_path / "selected")
    source = artifact.dump_path
    if case == "wrong":
        source.write_bytes(b"incorrect dump bytes")
    elif case == "empty":
        source.write_bytes(b"")
    elif case == "relative":
        artifact.dump_path = Path("relative.dump")
    elif case == "symlink":
        original = source.with_suffix(".original")
        source.rename(original)
        source.symlink_to(original)
    elif case == "hardlink":
        os.link(source, source.with_suffix(".linked"))
    elif case == "fifo":
        source.unlink()
        os.mkfifo(source, 0o600)
    elif case == "directory":
        source.unlink()
        source.mkdir(mode=0o700)
    elif case == "mode":
        source.chmod(0o644)
    elif case == "owner":
        original_fstat = snapshots.os.fstat
        identity = source.stat()
        def wrong_owner(fd):
            info = original_fstat(fd)
            if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
                values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
                values["st_uid"] = info.st_uid + 1
                return SimpleNamespace(**values)
            return info
        monkeypatch.setattr(snapshots.os, "fstat", wrong_owner)
    else:
        # Keep selected/inner admission safe; only the dump lives in this directory.
        directory = tmp_path / "unsafe-source"
        directory.mkdir(mode=0o755)
        artifact.dump_path = private_write(directory / "database.dump", DUMP)
    scenario = RestoreScenario(tmp_path, artifact)
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()
    assert source.exists()


@pytest.mark.parametrize("operation", ["write", "zero_write", "fsync"])
def test_disk_failure_cleans_partial_owned_snapshot_without_effects(tmp_path, monkeypatch, operation):
    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    name = "fsync" if operation == "fsync" else "write"
    original = getattr(snapshots.os, name)
    create = snapshots._DumpSnapshot.create
    snapshot_fds = set()
    def remember(snapshot):
        create(snapshot)
        snapshot_fds.update((snapshot.file_fd, snapshot.dir_fd, snapshot.root_fd))
    monkeypatch.setattr(snapshots._DumpSnapshot, "create", remember)
    triggered = []
    def fail_once(*args):
        if args[0] in snapshot_fds and not triggered:
            triggered.append(True)
            if operation == "zero_write":
                return 0
            raise OSError(errno.ENOSPC, "injected disk failure")
        return original(*args)
    monkeypatch.setattr(snapshots.os, name, fail_once)
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    assert triggered
    scenario.assert_before_effects()
    assert artifact.dump_path.read_bytes() == DUMP


def test_partial_writes_make_progress_and_copy_is_bounded(tmp_path, monkeypatch):
    dump = b"custom dump bytes" * 150000
    artifact = SelectedArtifact(tmp_path / "selected", dump=dump)
    scenario = RestoreScenario(tmp_path, artifact)
    original = snapshots.os.write
    sizes = []
    create = snapshots._DumpSnapshot.create
    snapshot_fds = set()
    def remember(snapshot):
        create(snapshot)
        snapshot_fds.add(snapshot.file_fd)
    monkeypatch.setattr(snapshots._DumpSnapshot, "create", remember)
    def short_write(fd, data):
        if fd in snapshot_fds:
            sizes.append(len(data))
            return original(fd, data[:max(1, len(data) // 2)])
        return original(fd, data)
    monkeypatch.setattr(snapshots.os, "write", short_write)
    scenario.database.restore = lambda _sibling, path: Path(path).read_bytes() == dump or pytest.fail("wrong copy")
    scenario.run()
    assert len(sizes) > 2
    assert max(sizes) <= snapshots.CHUNK_BYTES
    assert artifact.dump_path.read_bytes() == dump


@pytest.mark.parametrize("case", ["ops_mode", "ancestor_mode", "missing_dump_method", "unsupported_dump_method"])
def test_snapshot_preparation_has_no_filesystem_or_adapter_fallback(tmp_path, case):
    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    if case == "ops_mode":
        scenario.ops.mkdir(mode=0o700)
        scenario.ops.chmod(0o777)
    elif case == "ancestor_mode":
        unsafe = tmp_path / "unsafe"
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        scenario.ops = unsafe / "ops"
        scenario.writers.ops = scenario.ops
    elif case == "missing_dump_method":
        artifact.database_dump_path = None
    else:
        def unsupported():
            raise NotImplementedError("no dump staging capability")
        artifact.database_dump_path = unsupported
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()
    assert artifact.dump_path.read_bytes() == DUMP


def test_private_source_parent_alias_still_consumes_authenticated_owned_snapshot(tmp_path):
    artifact = SelectedArtifact(tmp_path / "selected")
    original = artifact.dump_path
    alias = tmp_path / "source-alias"
    alias.symlink_to(original.parent, target_is_directory=True)
    artifact.dump_path = alias / original.name
    scenario = RestoreScenario(tmp_path, artifact)
    consumed = []
    def restore(_sibling, path):
        copied = Path(path)
        assert copied != artifact.dump_path and copied.read_bytes() == DUMP
        assert stat.S_IMODE(copied.stat().st_mode) == 0o600
        assert stat.S_IMODE(copied.parent.stat().st_mode) == 0o700
        consumed.append(copied)
    scenario.database.restore = restore
    scenario.run()
    assert len(consumed) == 1 and not consumed[0].exists()
    assert alias.is_symlink() and original.read_bytes() == DUMP
