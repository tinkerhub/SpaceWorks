"""Both phase states compare every minimal binding before any effect or shortcut."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from apps.backup.host_run_ledger import RunLedgerError

from apps.tenant_migration.tenant_restore_artifact_admission import read_selected_artifact_context
from apps.tenant_migration.tenant_restore_client_admission import validate_client_request
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused
from tests.tenant_migration.x12_restore_test_helpers import RestoreScenario
from tests.tenant_migration.x12_selected_test_helpers import (
    SelectedArtifact, admission_inner, approvals_for, catalog, catalog_entry, rehash_approval,
)

BINDING_CHANGES = {
    "artifact_sha256": "f" * 64, "outer_version": 1,
    "capture_id": "00000000-0000-0000-0000-000000000001", "inner_manifest_sha256": "e" * 64,
    "projection_mode": "legacy_unverified", "projection_proof_sha256": "d" * 64,
    "database_member_sha256": "c" * 64, "api_client_catalog_sha256": "b" * 64,
    "api_client_approvals_sha256": "a" * 64, "api_client_reissue_requested": False,
}


def bindings_for(scenario):
    context = read_selected_artifact_context(scenario.inputs, scenario.artifact)
    request = validate_client_request(scenario.inputs, context, scenario.target)
    return {**context.ledger_bindings(), **request.ledger_bindings()}


def seed_binding(scenario, phase, state, bindings):
    scenario.ops.mkdir(mode=0o700, exist_ok=True)
    begun = scenario.ledger().begin(phase, {"artifact_bindings": bindings})
    if state == "done":
        scenario.ledger().finish(begun)


@pytest.mark.parametrize("phase", ["static-preflight", "api-client-reissue"])
@pytest.mark.parametrize("state", ["begun", "done"])
@pytest.mark.parametrize("binding", BINDING_CHANGES)
def test_every_binding_is_compared_in_both_relevant_phase_states(tmp_path, phase, state, binding):
    artifact = SelectedArtifact(tmp_path / "selected", inner=admission_inner(clients=catalog(catalog_entry())))
    scenario = RestoreScenario(tmp_path, artifact)
    scenario.target.reissue_validated_api_clients = lambda *a, **k: pytest.fail("resume changed")
    scenario.inputs = replace(scenario.inputs, api_client_approvals=approvals_for(artifact))
    original = bindings_for(scenario)
    if phase == "api-client-reissue":
        seed_binding(scenario, "static-preflight", "done", original)
    changed = dict(original, **{binding: BINDING_CHANGES[binding]})
    seed_binding(scenario, phase, state, changed)
    before = scenario.ledger_path.read_bytes()
    with pytest.raises(TenantRestoreRefused, match="changed on resume"):
        scenario.run()
    assert scenario.events == []
    assert scenario.ledger_path.read_bytes() == before
    assert not scenario.marker.exists()
    assert artifact.reads[-2:] == ["selected", "inner"]
    assert "dump" not in artifact.reads


@pytest.mark.parametrize("phase", ["static-preflight", "api-client-reissue"])
@pytest.mark.parametrize("state", ["begun", "done"])
@pytest.mark.parametrize("was_requested", [False, True])
def test_empty_nonempty_request_change_cannot_silently_skip(tmp_path, phase, state, was_requested):
    artifact = SelectedArtifact(tmp_path / "selected", inner=admission_inner(clients=catalog(catalog_entry())))
    scenario = RestoreScenario(tmp_path, artifact)
    scenario.target.reissue_validated_api_clients = lambda *a, **k: pytest.fail("request changed")
    approval = approvals_for(artifact)
    scenario.inputs = replace(scenario.inputs, api_client_approvals=approval if was_requested else None)
    original = bindings_for(scenario)
    if phase == "api-client-reissue":
        seed_binding(scenario, "static-preflight", "done", original)
    seed_binding(scenario, phase, state, original)
    scenario.inputs = replace(scenario.inputs, api_client_approvals={"approvals": []} if was_requested else approval)
    before = scenario.ledger_path.read_bytes()
    with pytest.raises(TenantRestoreRefused, match="changed on resume"):
        scenario.run()
    assert scenario.events == []
    assert scenario.ledger_path.read_bytes() == before


@pytest.mark.parametrize("phase", ["static-preflight", "api-client-reissue"])
@pytest.mark.parametrize("state", ["begun", "done"])
def test_expiry_is_rechecked_before_existing_phase_shortcut(tmp_path, monkeypatch, phase, state):
    from apps.tenant_migration import tenant_restore_api_clients as parser

    artifact = SelectedArtifact(tmp_path / "selected", inner=admission_inner(clients=catalog(catalog_entry())))
    scenario = RestoreScenario(tmp_path, artifact)
    now = datetime.now(timezone.utc)
    scenario.inputs = replace(scenario.inputs, api_client_approvals=approvals_for(artifact, now=now))
    scenario.target.reissue_validated_api_clients = lambda *a, **k: pytest.fail("expired request")
    original = bindings_for(scenario)
    if phase == "api-client-reissue":
        seed_binding(scenario, "static-preflight", "done", original)
    seed_binding(scenario, phase, state, original)
    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(hours=2)
    monkeypatch.setattr(parser, "datetime", ExpiredClock)
    before = scenario.ledger_path.read_bytes()
    with pytest.raises(TenantRestoreRefused, match="expired"):
        scenario.run()
    assert scenario.events == []
    assert scenario.ledger_path.read_bytes() == before


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("phase", ["static-preflight", "api-client-reissue"])
@pytest.mark.parametrize("state", ["begun", "done"])
def test_historical_missing_binding_is_only_actual_v1_no_request(tmp_path, version, phase, state):
    artifact = SelectedArtifact(tmp_path / "selected", version=version)
    scenario = RestoreScenario(tmp_path, artifact)
    scenario.ops.mkdir(mode=0o700, exist_ok=True)
    if phase == "api-client-reissue":
        begun = scenario.ledger().begin("static-preflight", {"historical": True})
        scenario.ledger().finish(begun)
    begun = scenario.ledger().begin(phase, {"historical": True})
    if state == "done":
        scenario.ledger().finish(begun)
    if version == 1:
        scenario.run()
        assert "restore" in scenario.events
    else:
        before = scenario.ledger_path.read_bytes()
        with pytest.raises(TenantRestoreRefused, match="changed on resume"):
            scenario.run()
        assert scenario.events == []
        assert scenario.ledger_path.read_bytes() == before


def test_completed_real_run_rereads_changed_selected_artifact_before_all_shortcuts(tmp_path):
    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    scenario.run()
    before = scenario.ledger_path.read_bytes()
    scenario.events.clear()
    artifact.path.write_bytes(b"replaced selected artifact")
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    assert scenario.events == []
    assert scenario.ledger_path.read_bytes() == before


def test_new_selected_artifact_sha_on_existing_run_keeps_host_ledger_refusal(tmp_path):
    artifact = SelectedArtifact(tmp_path / "selected")
    scenario = RestoreScenario(tmp_path, artifact)
    seed_binding(scenario, "static-preflight", "done", bindings_for(scenario))
    before = scenario.ledger_path.read_bytes()
    replacement = SelectedArtifact(tmp_path / "replacement", inner=admission_inner(clients=catalog(catalog_entry())))
    scenario.artifact = replacement
    scenario.inputs = replace(scenario.inputs, artifact_sha256=replacement.inputs.artifact_sha256)
    with pytest.raises(RunLedgerError, match="identity mismatch"):
        scenario.run()
    assert scenario.events == []
    assert scenario.ledger_path.read_bytes() == before
