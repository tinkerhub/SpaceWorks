"""Optional requests never revive the old opaque callback or journal secrets."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.tenant_migration.tenant_restore_artifact_admission import read_selected_artifact_context
from apps.tenant_migration.tenant_restore_client_admission import validate_client_request
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused, ValidatedApiClientTargetAdapter
from tests.tenant_migration.x12_restore_test_helpers import RestoreScenario
from tests.tenant_migration.x12_selected_test_helpers import (
    SelectedArtifact, admission_inner, approvals_for, catalog, catalog_entry, rehash_approval,
)


def requested_artifact(tmp_path):
    return SelectedArtifact(tmp_path / "selected", inner=admission_inner(clients=catalog(catalog_entry())))


@pytest.mark.parametrize("document", [None, {"approvals": []}, {"version": 1, "approvals": []}])
def test_no_request_finishes_zero_without_either_reissue_callback(tmp_path, document):
    artifact = requested_artifact(tmp_path)
    scenario = RestoreScenario(tmp_path, artifact)
    scenario.inputs = replace(scenario.inputs, api_client_approvals=document)
    scenario.target.reissue_validated_api_clients = lambda *a, **k: pytest.fail("no callback for empty approval")
    scenario.run()
    rows = [row for row in scenario.ledger().records() if row["phase"] == "api-client-reissue"]
    assert [row["state"] for row in rows] == ["begun", "done"]
    assert rows[-1]["detail"]["reissued"] == 0
    assert rows[-1]["detail"]["status"] == "not_requested"
    assert rows[-1]["detail"]["artifact_bindings"]["api_client_reissue_requested"] is False
    assert artifact.reads == ["selected", "inner", "dump"]
    before = scenario.ledger_path.read_bytes()
    scenario.inputs = replace(scenario.inputs, api_client_approvals=None if document else {"version": 1, "approvals": []})
    scenario.run()
    assert scenario.ledger_path.read_bytes() == before
    assert artifact.reads == ["selected", "inner", "dump"] * 2


@pytest.mark.parametrize("document", [False, [], {}, {"approvals": None}, {"approvals": ()},
                                     {"version": True, "approvals": []}, {"version": 2, "approvals": []},
                                     {"approvals": [], "ignored": True}, {"approvals": [None]}])
def test_malformed_non_none_request_refuses_before_effects(tmp_path, document):
    artifact = requested_artifact(tmp_path)
    scenario = RestoreScenario(tmp_path, artifact)
    scenario.inputs = replace(scenario.inputs, api_client_approvals=document)
    scenario.target.reissue_validated_api_clients = lambda *a, **k: pytest.fail("malformed request")
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()


@pytest.mark.parametrize("target", [SimpleNamespace(), SimpleNamespace(reissue_validated_api_clients=True),
                                    ValidatedApiClientTargetAdapter])
def test_nonempty_request_requires_dedicated_concrete_capability(tmp_path, target):
    artifact = requested_artifact(tmp_path)
    scenario = RestoreScenario(tmp_path, artifact)
    if target is ValidatedApiClientTargetAdapter:
        class InheritedStub(ValidatedApiClientTargetAdapter):
            pass
        target = InheritedStub()
    scenario.target = target
    scenario.inputs = replace(scenario.inputs, api_client_approvals=approvals_for(artifact))
    with pytest.raises(TenantRestoreRefused, match="does not support"):
        scenario.run()
    scenario.assert_before_effects()


@pytest.mark.parametrize("field,value", [
    ("artifact_sha256", "a" * 64), ("capture_id", "00000000-0000-0000-0000-000000000001"),
    ("source_catalog_sha256", "b" * 64), ("source_client_ref", "3" * 64),
    ("source_entry_sha256", "c" * 64), ("label", "changed"), ("client_type", "server"),
    ("rate_limit_tier", "trusted"), ("host_principal", ""), ("host_principal", "operator\x00"),
    ("nonce", ""), ("nonce", "\ud800"), ("privileged_scopes_approved", 1),
    ("target_scopes", ["public:write"]), ("target_scopes", ["unknown:scope"]),
    ("target_origins", ["https://user:secret@example.test"]),
    ("target_origins", ["https://target.example.test/path"]),
])
def test_nonempty_approval_bindings_attribution_and_scope_are_not_optional(tmp_path, field, value):
    artifact = requested_artifact(tmp_path)
    scenario = RestoreScenario(tmp_path, artifact)
    document = approvals_for(artifact)
    record = document["approvals"][0]
    record[field] = value
    try:
        rehash_approval(record)
    except UnicodeError:
        pass
    scenario.inputs = replace(scenario.inputs, api_client_approvals=document)
    scenario.target.reissue_validated_api_clients = lambda *a, **k: pytest.fail("invalid record")
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()


@pytest.mark.parametrize("case", ["expiry", "future", "naive", "hash", "duplicate_reference", "duplicate_nonce"])
def test_approval_expiry_hash_and_uniqueness_are_checked_before_effects(tmp_path, case):
    clients = catalog(catalog_entry(), catalog_entry(source_client_ref="2" * 64))
    artifact = SelectedArtifact(tmp_path / "selected", inner=admission_inner(clients=clients))
    scenario = RestoreScenario(tmp_path, artifact)
    document = approvals_for(artifact)
    record = document["approvals"][0]
    now = datetime.now(timezone.utc)
    if case == "expiry":
        record["expires_at"] = (now - timedelta(seconds=1)).isoformat()
    elif case == "future":
        record["approved_at"] = (now + timedelta(minutes=5)).isoformat()
    elif case == "naive":
        record["expires_at"] = datetime.now().isoformat()
    elif case == "duplicate_reference":
        document["approvals"][1] = dict(record, nonce="distinct-nonce")
        rehash_approval(document["approvals"][1])
    elif case == "duplicate_nonce":
        document["approvals"][1]["nonce"] = record["nonce"]
        rehash_approval(document["approvals"][1])
    rehash_approval(record)
    if case == "hash":
        record["approval_record_sha256"] = "0" * 64
    scenario.inputs = replace(scenario.inputs, api_client_approvals=document)
    scenario.target.reissue_validated_api_clients = lambda *a, **k: pytest.fail("invalid approvals")
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()


def test_validated_records_are_deeply_frozen_and_provider_return_is_redacted(tmp_path):
    artifact = requested_artifact(tmp_path)
    scenario = RestoreScenario(tmp_path, artifact)
    document = approvals_for(artifact)
    scenario.inputs = replace(scenario.inputs, api_client_approvals=document)
    calls = []
    def bridge(sibling, inputs, *, approved_records, source_catalog_sha256, approval_records_sha256):
        assert isinstance(approved_records, tuple)
        assert isinstance(approved_records[0]["target_scopes"], tuple)
        with pytest.raises(TypeError):
            approved_records[0]["label"] = "mutated"
        with pytest.raises(TypeError):
            approved_records[0]["target_scopes"][0] = "admin:read"
        calls.append((source_catalog_sha256, approval_records_sha256))
        return {"client_secret": "new-provider-secret-never-journal", "path": "/private/credential"}
    scenario.target.reissue_validated_api_clients = bridge
    context = read_selected_artifact_context(scenario.inputs, artifact)
    request = validate_client_request(scenario.inputs, context, scenario.target)
    saved_document = deepcopy(document)
    document["approvals"][0]["target_scopes"].append("admin:read")
    assert request.approved_records[0]["target_scopes"] == ("public:read",)
    # Restore with the original valid document; the preflight parses independently.
    scenario.inputs = replace(scenario.inputs, api_client_approvals=saved_document)
    scenario.run()
    assert calls == [(context.api_client_catalog["sha256"], request.approval_records_sha256)]
    ledger = scenario.ledger_path.read_text()
    for forbidden in ("new-provider-secret", "/private/credential", "Source kiosk", "source.example.test",
                      "x12-host-operator", "target_scopes", "x12-nonce"):
        assert forbidden not in ledger
