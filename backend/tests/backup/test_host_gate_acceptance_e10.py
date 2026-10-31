"""Static admission cannot substitute for installed host capability validation."""

from contextlib import nullcontext
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from apps.backup import compound_restore_coordinator as coordinator
from apps.backup import compound_restore_preflight as preflight
from apps.backup import import_preflight
from apps.backup.compound_protocol import PROTOCOL_VERSION
from apps.backup.compound_restore_types import CompoundRestoreRefused
from tests.backup.e9b_coordinator_test_support import Database, inputs
from tests.backup.test_host_restore_capability_e9b import installed_capability_case


def test_static_host_gate_status_is_fresh_non_authoritative_and_does_not_probe(monkeypatch):
    probe = Mock(side_effect=AssertionError("static status probed the host"))
    monkeypatch.setattr("apps.backup.host_restore_capability.InstalledHostCapability.validate", probe)
    monkeypatch.setattr("subprocess.run", probe)
    status = import_preflight.host_restore_gate_status()
    assert status == {"state": "not_checked", "admission": "static-artifact-only", "authority": False}
    status["state"] = "forged-validated"
    assert import_preflight.host_restore_gate_status() == {
        "state": "not_checked", "admission": "static-artifact-only", "authority": False,
    }
    probe.assert_not_called()


def _admission(monkeypatch, *, topology, manifest=None, status=None):
    selected = inputs()
    result = import_preflight.ImportPreflightResult(
        manifest={**(manifest or {}), "capture_id": selected.capture_id},
        archive_sha256=selected.artifact_sha256,
        host_restore_gate=status or import_preflight.host_restore_gate_status(),
    )
    monkeypatch.setattr(preflight, "validate_import_preflight", lambda **_kwargs: result)
    events = []
    pointer = SimpleNamespace(
        preflight=lambda **_kwargs: topology, current_generation=lambda: 1,
    )
    return selected, pointer, Database(events), events


def test_real_installed_private_capability_yields_validated_v2_status(monkeypatch, tmp_path):
    capability, topology, manifest, _script, record = installed_capability_case(tmp_path)
    selected, pointer, database, events = _admission(
        monkeypatch, topology=topology, manifest=manifest,
    )
    result, actual_topology, facts = preflight.validate_compound_preflight(
        selected, pointer=pointer, database=database, capability=capability,
    )
    # Hash the installed record independently of capability.validate's return.
    record_digest = hashlib.sha256(json.dumps(
        json.loads(record.read_text()), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    assert result.host_restore_gate == {
        "state": "validated", "authority": True,
        "compound_protocol": "spaceworks-lane-e-b1-v2",
        "record_sha256": record_digest,
        "migration_version": "backup.0022_target_import_recovery_mode",
    }
    assert facts["record_sha256"] == record_digest
    assert actual_topology == topology
    assert events == []


def _refused_before_effect(monkeypatch, tmp_path, capability, *, topology, manifest=None, status=None):
    selected, pointer, database, events = _admission(
        monkeypatch, topology=topology, manifest=manifest, status=status,
    )
    ledger = Mock()
    ledger.records.return_value = []
    monkeypatch.setattr(coordinator, "supervise_run", lambda *_args, **_kwargs: nullcontext(
        SimpleNamespace(ledger=ledger),
    ))
    # Keep the actual compound preflight; every effect adapter is an observable spy.
    effects = Mock()
    with pytest.raises(CompoundRestoreRefused):
        coordinator.run_compound_restore(
            ops_dir=tmp_path / "ops", inputs=selected, artifact=effects,
            database=database, pointer=pointer, writers=effects, target=effects,
            object_store=effects, capability=capability, capability_journal=effects,
            marker_writer=effects, require_root_owned=False,
        )
    assert ledger.mock_calls
    assert all(item == call.records() for item in ledger.mock_calls)
    assert effects.mock_calls == []
    assert events == []
    assert not (tmp_path / "ops").exists()


@pytest.mark.parametrize("case", [
    "missing", "not-dict", "false-validation", "missing-protocol", "wrong-protocol",
    "missing-digest", "bad-digest", "missing-migration", "empty-migration", "typed-migration",
])
def test_missing_or_malformed_actual_capability_facts_refuse_before_first_effect(
    monkeypatch, tmp_path, case,
):
    _capability, topology, _manifest, _script, _record = installed_capability_case(tmp_path)
    facts = {"validated": True, "compound_protocol": PROTOCOL_VERSION,
             "record_sha256": "a" * 64, "migration_version": "fixture-migrations-v2"}
    if case == "missing":
        facts = None
    elif case == "not-dict":
        facts = "validated"
    elif case == "false-validation":
        facts["validated"] = 1
    else:
        field = {"protocol": "compound_protocol", "digest": "record_sha256",
                 "migration": "migration_version"}[case.split("-")[-1]]
        if case.startswith("missing-"):
            facts.pop(field)
        else:
            facts[field] = {"wrong-protocol": "spaceworks-lane-e-b1-v1", "bad-digest": "xyz",
                            "empty-migration": " ", "typed-migration": 7}[case]
    capability = SimpleNamespace(validate=lambda **_kwargs: facts)
    _refused_before_effect(monkeypatch, tmp_path, capability, topology=topology)


def test_forged_descriptive_status_cannot_bypass_real_capability_denial(monkeypatch, tmp_path):
    capability, topology, manifest, script, _record = installed_capability_case(tmp_path)
    script.write_bytes(b"installed script differs from signed record")
    _refused_before_effect(
        monkeypatch, tmp_path, capability, topology=topology, manifest=manifest,
        status={"state": "validated", "authority": True, "compound_protocol": PROTOCOL_VERSION,
                "record_sha256": "f" * 64, "migration_version": "forged"},
    )


@pytest.mark.parametrize("case", ["missing-record", "malformed-record", "protocol", "signer", "migration", "writers"])
def test_installed_capability_record_checks_precede_validated_status_and_effects(
    monkeypatch, tmp_path, case,
):
    capability, topology, manifest, _script, record = installed_capability_case(tmp_path)
    if case == "missing-record":
        record.unlink()
    elif case == "malformed-record":
        record.write_text("{invalid-json")
    else:
        payload = json.loads(record.read_text())
        field, value = {
            "protocol": ("compound_protocol", "spaceworks-lane-e-b1-v1"),
            "signer": ("signing_key_fingerprint", "f" * 64),
            "migration": ("migration_version", "different-migration"),
            "writers": ("writer_set", ["backend"]),
        }[case]
        payload[field] = value
        record.write_text(json.dumps(payload))
    _refused_before_effect(
        monkeypatch, tmp_path, capability, topology=topology, manifest=manifest,
    )
