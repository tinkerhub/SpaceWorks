"""Real capture lifecycle with local files and fake projection effects only."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.backup import compound_archive
from apps.backup.digests import sha256_file
from apps.backup.errors import BackupBuildError
from apps.backup.source_capture_facts import require_source_capture_facts


def _capture(monkeypatch, tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "database.dump").write_bytes(b"frozen source dump")
    capture = compound_archive.CompoundCapture(
        archive=SimpleNamespace(pk=17), root=root, modes={}, platform_recipients=[],
    )
    assert capture.source_capture_facts is None
    capture.expected_main_ledger = {"catalog": "expected"}
    capture.source_database_identity = "source-database"
    capture.source_server_identity = "postgresql:160010:701"
    capture.source_dump_sha256 = sha256_file(root / "database.dump")
    capture.frozen_population = ({"makerspace_id": 701},)
    capture.reservation_capture = SimpleNamespace(bind_object_plan=lambda *_args: capture.reservation_capture)
    plan = SimpleNamespace(references=(), assert_complete=Mock(), verify_component=Mock())
    monkeypatch.setattr(compound_archive, "closure_digest_from_slice_ledgers", lambda _slices: "c" * 64)
    capture.capture_from_snapshot(
        tenant_payload=Mock(), capture_objects=Mock(), write_json=Mock(), object_plan=plan,
    )
    plan.assert_complete.assert_called_once_with()
    return capture


def test_real_capture_freezes_once_and_refuses_replacement(monkeypatch, tmp_path):
    capture = _capture(monkeypatch, tmp_path)
    facts = require_source_capture_facts(capture)
    assert facts.source_database_identity == "source-database"
    assert facts.frozen_dump_sha256 == sha256_file(capture.root / "database.dump")
    with pytest.raises(BackupBuildError, match="cannot be replaced"):
        capture.source_capture_facts = facts
    with pytest.raises(FrozenInstanceError):
        facts.frozen_dump_sha256 = "0" * 64
    with pytest.raises(BackupBuildError, match="already frozen"):
        capture.capture_from_snapshot(
            tenant_payload=Mock(), capture_objects=Mock(), write_json=Mock(), object_plan=capture.object_plan,
        )


def test_changed_database_dump_refuses_before_projection_or_rename(monkeypatch, tmp_path):
    capture = _capture(monkeypatch, tmp_path)
    (capture.root / "database.dump").write_bytes(b"changed source dump")
    projection, reconstruction, signing = Mock(), Mock(), Mock()
    monkeypatch.setattr(compound_archive, "project_readable_main_dump", projection)
    monkeypatch.setattr(compound_archive, "verify_reconstruction", reconstruction)
    monkeypatch.setattr(compound_archive, "verify_and_sign_source_partition", signing)
    with pytest.raises(BackupBuildError, match="frozen source dump changed"):
        capture.project_readable_main({})
    assert not (capture.root / ".main-build").exists()
    assert (capture.root / "database.dump").read_bytes() == b"changed source dump"
    projection.assert_not_called()
    reconstruction.assert_not_called()
    signing.assert_not_called()


def test_changed_source_dump_during_projection_refuses_before_signing(monkeypatch, tmp_path):
    capture = _capture(monkeypatch, tmp_path)
    capture.reservation_capture.sequence_facts = ()

    def project(source, destination, *_args, **_kwargs):
        source.write_bytes(b"altered retained source.dump")
        destination.write_bytes(b"readable main")

    signing = Mock()
    monkeypatch.setattr(compound_archive, "project_readable_main_dump", project)
    monkeypatch.setattr(compound_archive, "verify_reconstruction", Mock())
    monkeypatch.setattr(compound_archive, "table_rules", lambda: ())
    monkeypatch.setattr(compound_archive, "server_major", lambda: 16)
    monkeypatch.setattr(compound_archive, "verify_and_sign_source_partition", signing)
    with pytest.raises(BackupBuildError, match="frozen source dump changed"):
        capture.project_readable_main({"storage": {"objects": []}})
    signing.assert_not_called()
    assert not (capture.root / ".main-build").exists()


def test_frozen_fact_detects_in_place_population_mutation(monkeypatch, tmp_path):
    capture = _capture(monkeypatch, tmp_path)
    capture.frozen_population[0]["makerspace_id"] = 999
    with pytest.raises(BackupBuildError, match="changed after freezing"):
        require_source_capture_facts(capture)


def test_projection_requires_freeze_before_any_projection_effect(tmp_path, monkeypatch):
    capture = compound_archive.CompoundCapture(
        archive=SimpleNamespace(pk=17), root=tmp_path, modes={}, platform_recipients=[],
    )
    project = Mock()
    monkeypatch.setattr(compound_archive, "project_readable_main_dump", project)
    with pytest.raises(BackupBuildError, match="facts are missing"):
        capture.project_readable_main({})
    project.assert_not_called()
    assert not (tmp_path / ".main-build").exists()
