"""Consume identity's selected-artifact API; FD/age adversarial tests stay owned there."""

import pytest
from types import SimpleNamespace

from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused
from apps.tenant_migration.tenant_restore_client_admission import validate_client_request
from .x13_proof_helpers import (
    complete_admission_inner, protocol_record, rehash, selected_context,
)


def test_selected_actual_v1_reports_legacy_without_inventing_projection_evidence(tmp_path):
    inner = protocol_record()
    inner.pop("projection_verification")
    context = selected_context(tmp_path, inner, version=1)
    assert context.outer_version == 1
    assert context.projection_mode == "legacy_unverified"
    assert context.projection_proof_sha256 is None
    assert context.database_member_sha256 is None
    no_reissue = validate_client_request(SimpleNamespace(api_client_approvals=None), context, object())
    assert not no_reissue.requested and no_reissue.approved_records == ()
    with pytest.raises(TenantRestoreRefused, match="requires an authenticated v2"):
        validate_client_request(SimpleNamespace(api_client_approvals={"approvals": [
            {"source_client_ref": "0" * 64},
        ]}), context, object())


def test_selected_actual_v2_uses_its_proof_despite_caller_legacy_claims(tmp_path):
    inner = complete_admission_inner(protocol_record())
    context = selected_context(tmp_path, inner)
    assert context.outer_version == 2
    assert context.projection_mode == "verified_v1"
    assert context.projection_proof_sha256 == inner["projection_verification"]["sha256"]
    assert context.database_member_sha256 == inner["contents"][0]["sha256"]
    assert context.ledger_bindings()["projection_mode"] == "verified_v1"


@pytest.mark.parametrize("corruption", ["missing", "unknown_version", "dump_binding", "semantic_digest"])
def test_selected_v2_valid_outer_and_inner_hashes_cannot_hide_bad_projection_proof(tmp_path, corruption):
    inner = complete_admission_inner(protocol_record())
    if corruption == "missing":
        inner.pop("projection_verification")
    else:
        proof = inner["projection_verification"]
        field, value = {"unknown_version": ("version", 27), "dump_binding": ("database_member_sha256", "0" * 64),
                        "semantic_digest": ("semantic_references_sha256", "0" * 64)}[corruption]
        proof[field] = value
        rehash(proof)
    # selected_context computes the actual artifact and exact inner-buffer hashes
    # *after* corruption. This failure is the proof contract, not stale outer bytes.
    with pytest.raises(TenantRestoreRefused) as refused:
        selected_context(tmp_path, inner)
    causes = []
    cause = refused.value
    while cause is not None:
        causes.append(str(cause))
        cause = cause.__cause__
    assert any("projection verification record" in message for message in causes)
