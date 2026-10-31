"""Copy drift, late snapshot refusal, conservative cleanup and fresh resume proof."""

from contextlib import contextmanager
from pathlib import Path
import os

import pytest

from apps.tenant_migration import tenant_restore_dump_snapshot as snapshots
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused
from tests.tenant_migration.x12_restore_test_helpers import RestoreScenario
from tests.tenant_migration.x12_selected_test_helpers import DUMP, SelectedArtifact, private_write


@pytest.mark.parametrize("change", ["truncate", "grow", "same_size"])
def test_original_descriptor_drift_during_copy_refuses_before_ledger(tmp_path, monkeypatch, change):
    artifact = SelectedArtifact(tmp_path / "selected", dump=b"A" * (snapshots.CHUNK_BYTES + 7))
    scenario = RestoreScenario(tmp_path, artifact)
    original = snapshots.open_artifact_file
    @contextmanager
    def drift(path, **kwargs):
        with original(path, **kwargs) as source:
            class ReadAndChange:
                changed = False
                def fileno(self):
                    return source.fileno()
                def read(self, size):
                    data = source.read(size)
                    assert size <= snapshots.CHUNK_BYTES
                    if not self.changed:
                        self.changed = True
                        with Path(path).open("r+b") as writer:
                            if change == "truncate":
                                writer.truncate(1)
                            elif change == "grow":
                                writer.seek(0, 2)
                                writer.write(b"growth")
                            else:
                                writer.write(b"B")
                    return data
            yield ReadAndChange()
    monkeypatch.setattr(snapshots, "open_artifact_file", drift)
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()


@pytest.mark.parametrize("change", ["inplace", "symlink", "replace", "chmod", "hardlink", "directory_swap"])
def test_snapshot_is_rechecked_immediately_before_actual_restore(tmp_path, change):
    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    foreign = private_write(tmp_path / "foreign", b"foreign content must survive")
    saved = []
    original = scenario.writers.persist_offline
    def mutate(*args):
        snapshot = next(scenario.ops.glob(".tenant-restore-dump-*/database.dump"))
        saved.append(snapshot)
        if change == "inplace":
            snapshot.write_bytes(b"X" * len(DUMP))
        elif change in {"symlink", "replace"}:
            snapshot.unlink()
            if change == "symlink":
                snapshot.symlink_to(foreign)
            else:
                private_write(snapshot, b"foreign replacement")
        elif change == "chmod":
            snapshot.chmod(0o640)
        elif change == "hardlink":
            os.link(snapshot, snapshot.parent / "foreign-link")
        elif change == "directory_swap":
            moved = snapshot.parent.with_name(snapshot.parent.name + ".moved")
            snapshot.parent.rename(moved)
            snapshot.parent.mkdir(mode=0o700)
            private_write(snapshot, b"foreign replacement directory")
        return original(*args)
    scenario.writers.persist_offline = mutate
    called = []
    scenario.database.restore = lambda *_: called.append(True)
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    assert saved and not called
    assert "cutover" not in scenario.events
    assert foreign.read_bytes() == b"foreign content must survive"
    assert artifact.dump_path.read_bytes() == DUMP
    if change == "symlink":
        assert saved[0].is_symlink()
    elif change in {"replace", "directory_swap"}:
        assert saved[0].read_bytes().startswith(b"foreign replacement")


def test_digest_is_rechecked_even_if_metadata_guard_is_instrumented_stable(tmp_path, monkeypatch):
    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    original = scenario.writers.persist_offline
    def mutate(*args):
        next(scenario.ops.glob(".tenant-restore-dump-*/database.dump")).write_bytes(b"X" * len(DUMP))
        return original(*args)
    scenario.writers.persist_offline = mutate
    # Isolate the second independent guard: the real snapshot digest still has to match.
    monkeypatch.setattr(snapshots._DumpSnapshot, "_check_locations", lambda _: None)
    with pytest.raises(TenantRestoreRefused, match="validation"):
        scenario.run()
    assert "restore" not in scenario.events


@pytest.mark.parametrize("document", [None, {"version": 1, "approvals": []}])
def test_completed_restore_resume_still_reverifies_dump_before_any_skip(tmp_path, document):
    from dataclasses import replace

    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    scenario.inputs = replace(scenario.inputs, api_client_approvals=document)
    scenario.run()
    before = scenario.ledger_path.read_bytes()
    scenario.events.clear()
    artifact.dump_path.write_bytes(b"wrong original on completed resume")
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    assert scenario.events == []
    assert scenario.ledger_path.read_bytes() == before
    assert artifact.reads.count("selected") == 2
    assert artifact.reads.count("inner") == 2
    assert artifact.reads.count("dump") == 2
    assert not list(scenario.ops.glob(".tenant-restore-dump-*"))


def test_missing_snapshot_name_cleanup_does_not_delete_original(tmp_path):
    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    def consume(_sibling, path):
        assert Path(path).read_bytes() == DUMP
        Path(path).unlink()
    scenario.database.restore = consume
    scenario.run()
    assert artifact.dump_path.read_bytes() == DUMP
    assert not list(scenario.ops.glob(".tenant-restore-dump-*"))


def test_operations_directory_swap_after_restore_begin_refuses_before_adapter(tmp_path, monkeypatch):
    from apps.backup.host_run_ledger import RunLedger

    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    begin = RunLedger.begin
    moved = tmp_path / "old-ops"
    def begin_and_swap(ledger, phase, detail):
        record = begin(ledger, phase, detail)
        if phase == "database-restore":
            scenario.ops.rename(moved)
            scenario.ops.mkdir(mode=0o700)
            private_write(scenario.ops / "foreign-keep", b"foreign operations directory")
        return record
    monkeypatch.setattr(RunLedger, "begin", begin_and_swap)
    with pytest.raises(TenantRestoreRefused, match="validation"):
        scenario.run()
    assert "restore" not in scenario.events
    assert (scenario.ops / "foreign-keep").read_bytes() == b"foreign operations directory"
    assert artifact.dump_path.read_bytes() == DUMP
    assert not list(moved.glob(".tenant-restore-dump-*"))


@pytest.mark.parametrize("restore_fails", [False, True])
def test_cleanup_io_failure_is_typed_or_preserves_the_existing_restore_error(tmp_path, monkeypatch, restore_fails):
    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    original = snapshots.os.unlink
    def refuse_owned_unlink(path, *args, **kwargs):
        if path == "database.dump" and "dir_fd" in kwargs:
            raise OSError("injected unlink failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(snapshots.os, "unlink", refuse_owned_unlink)
    if restore_fails:
        def fail(_sibling, path):
            assert Path(path).read_bytes() == DUMP
            raise RuntimeError("original restore error")
        scenario.database.restore = fail
        with pytest.raises(RuntimeError, match="original restore error") as refused:
            scenario.run()
        assert any("snapshot cleanup failed" in note for note in refused.value.__notes__)
    else:
        with pytest.raises(TenantRestoreRefused, match="cleanup failed"):
            scenario.run()
    assert artifact.dump_path.read_bytes() == DUMP
    leftovers = list(scenario.ops.glob(".tenant-restore-dump-*/database.dump"))
    assert len(leftovers) == 1  # persistent unlink failure cannot promise deletion
    assert leftovers[0].read_bytes() == DUMP
