"""Every command admits actual selected bytes, even without client reissue."""

from dataclasses import FrozenInstanceError, replace
import json

import pytest

from apps.tenant_migration.tenant_restore_artifact_admission import read_selected_artifact_context
from apps.tenant_migration.tenant_restore_types import ArtifactPreflight, TenantRestoreRefused
from tests.tenant_migration.x12_restore_test_helpers import RestoreScenario
from tests.tenant_migration.x12_selected_test_helpers import (
    SelectedArtifact, admission_inner, catalog, catalog_entry, private_write, sha,
)


def test_v2_no_request_consumes_catalog_proof_and_frozen_minimal_context(tmp_path):
    artifact = SelectedArtifact(tmp_path / "selected")
    context = read_selected_artifact_context(artifact.inputs, artifact)
    assert context.outer_version == 2
    assert context.projection_mode == "verified_v1"
    assert context.projection_proof_sha256 == artifact.inner["projection_verification"]["sha256"]
    assert context.database_member_sha256 == sha(artifact.dump_path.read_bytes())
    assert artifact.reads == ["selected", "inner"]
    with pytest.raises(FrozenInstanceError):
        context.outer_version = 1
    with pytest.raises(TypeError):
        context.api_client_catalog["entries"] = ()
    assert not hasattr(context, "inner_manifest")
    assert not hasattr(context, "inner_manifest_path")


@pytest.mark.parametrize("method", ["selected_artifact_path", "inner_manifest_path"])
@pytest.mark.parametrize("unsupported", [False, True])
def test_missing_mandatory_path_cannot_be_replaced_by_boolean_approval(tmp_path, method, unsupported):
    artifact = SelectedArtifact(tmp_path / "selected")
    def unsupported_method(_):
        raise NotImplementedError("unsupported mandatory path")
    setattr(artifact, method, unsupported_method if unsupported else None)
    scenario = RestoreScenario(tmp_path, artifact)
    scenario.inputs = replace(scenario.inputs, detail={"outer_version": 1, "legacy_unverified": True})
    with pytest.raises(TenantRestoreRefused, match=method):
        scenario.run()
    scenario.assert_before_effects()


@pytest.mark.parametrize("case", ["artifact", "inner", "catalog", "proof", "dump"])
def test_substitution_after_selection_refuses_before_first_effect(tmp_path, case):
    artifact = SelectedArtifact(tmp_path / "selected", inner=admission_inner(clients=catalog(catalog_entry())))
    if case == "artifact":
        data = artifact.path.read_bytes().replace(b"opaque framing", b"OPAQUE FRAMING")
        private_write(artifact.path, data)
    elif case == "dump":
        private_write(artifact.dump_path, b"wrong dump")
    else:
        inner = artifact.inner
        if case == "inner":
            inner["source"]["makerspace_id"] += 1
        elif case == "catalog":
            # A self-consistent replacement catalog is still not the selected inner.
            inner["api_client_catalog"] = catalog(catalog_entry(label="Replacement"))
        else:
            inner["projection_verification"]["database_member_sha256"] = "e" * 64
        private_write(artifact.inner_path, json.dumps(inner).encode())
    scenario = RestoreScenario(tmp_path, artifact)
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()


@pytest.mark.parametrize("case", [
    "missing_proof", "proof_digest", "capture", "source", "custody", "catalog_header",
    "database", "content_size", "content_order", "objects", "policy", "deployment",
])
def test_authenticated_incompatible_v2_inner_still_refuses(tmp_path, case):
    inner = admission_inner()
    if case == "missing_proof":
        inner.pop("projection_verification")
    elif case == "proof_digest":
        inner["projection_verification"]["sha256"] = "f" * 64
    elif case == "capture":
        inner["projection_verification"]["capture_id"] = "00000000-0000-0000-0000-000000000001"
    elif case == "source":
        inner["source"]["makerspace_id"] = True
    elif case == "custody":
        inner["encryption"]["tenant_dek_envelope"]["present"] = True
    elif case == "catalog_header":
        inner["api_client_catalog"]["version"] = True
    elif case == "database":
        inner["contents"][0]["sha256"] = "e" * 64
    elif case == "content_size":
        inner["contents"][0]["size"] = True
    elif case == "content_order":
        inner["contents"].reverse()
    elif case == "objects":
        inner["objects"] = [dict(member_path="objects/private/" + "a" * 64, size=1, sha256="b" * 64)]
    elif case == "policy":
        inner["lineage"]["derivation_policy_sha256"] = "b" * 64
    else:
        inner["source"]["deployment_identity"] = "stringified-identity-is-invalid"
    artifact = SelectedArtifact(tmp_path / "selected", inner=inner)
    scenario = RestoreScenario(tmp_path, artifact)
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()


@pytest.mark.parametrize("data", [b'{"capture_id":1,"capture_id":2}', b'{"value":NaN}', b'{"value":Infinity}'])
def test_authenticated_duplicate_and_nonfinite_json_refuses(tmp_path, data):
    artifact = SelectedArtifact(tmp_path / "selected", data=data)
    scenario = RestoreScenario(tmp_path, artifact)
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()


@pytest.mark.parametrize("case", ["unknown", "bool_version", "missing_inner_sha", "empty_compatibility", "extra_field"])
def test_selected_outer_has_exact_version_and_header(tmp_path, case):
    artifact = SelectedArtifact(tmp_path / "selected")
    def mutate(outer):
        if case == "unknown":
            outer["version"] = 3
        elif case == "bool_version":
            outer["version"] = True
        elif case == "missing_inner_sha":
            outer["compatibility"].pop("inner_manifest_sha256")
        elif case == "empty_compatibility":
            outer["compatibility"] = {}
        else:
            outer["adapter_verified"] = True
    artifact.replace_outer(mutate)
    scenario = RestoreScenario(tmp_path, artifact)
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()


def test_actual_v1_legacy_contract_is_explicit_and_nonempty_reissue_refuses(tmp_path):
    artifact = SelectedArtifact(tmp_path / "selected", version=1)
    # The legacy contract never consumes an inner path or manufactures dump proof.
    artifact.inner_manifest_path = lambda _: pytest.fail("v1 has no authenticated inner")
    context = read_selected_artifact_context(artifact.inputs, artifact)
    assert (context.outer_version, context.projection_mode) == (1, "legacy_unverified")
    assert context.database_member_sha256 is None
    scenario = RestoreScenario(tmp_path, artifact)
    original_restore = scenario.database.restore
    def restore(sibling, path):
        assert path == artifact.dump_path
        original_restore(sibling, path)
    scenario.database.restore = restore
    scenario.run()
    scenario.inputs = replace(scenario.inputs, api_client_approvals={"approvals": [{}]})
    before = scenario.ledger_path.read_bytes()
    scenario.events.clear()
    with pytest.raises(TenantRestoreRefused, match="authenticated v2"):
        scenario.run()
    assert scenario.events == []
    assert scenario.ledger_path.read_bytes() == before


@pytest.mark.parametrize("field", ArtifactPreflight.__dataclass_fields__)
def test_actual_v1_legacy_admission_still_requires_every_current_artifact_gate(tmp_path, field):
    artifact = SelectedArtifact(tmp_path / "selected", version=1)
    artifact.static_preflight = lambda _: replace(ArtifactPreflight(*([True] * 12)), **{field: False})
    scenario = RestoreScenario(tmp_path, artifact)
    with pytest.raises(TenantRestoreRefused):
        scenario.run()
    scenario.assert_before_effects()
