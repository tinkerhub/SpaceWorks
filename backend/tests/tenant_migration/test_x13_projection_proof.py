"""Strict proof metadata checks; these do not claim to reconstruct erased source."""

from copy import deepcopy
import hashlib
import json

import pytest

from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_dump_projection_proof import (
    PROOF_FIELDS, canonical_digest, validate_projection_record, validate_projection_verification,
)
from .x13_proof_helpers import protocol_record, outer_for_inner, rehash


def semantic_record(pk, location="json:type_payload"):
    return dict(model_label="machines.Machine", source_row_pk=pk, location=location,
                disposition="preserve", value_sha256=canonical_digest({"literal_user_id": 91}))


def test_exact_record_canonical_hash_and_frozen_facts():
    inner = protocol_record()
    proof = inner["projection_verification"]
    assert set(proof) == PROOF_FIELDS
    payload = {key: value for key, value in proof.items() if key != "sha256"}
    independent = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    assert proof["sha256"] == independent
    facts = validate_projection_record(inner)
    assert (facts.mode, facts.proof_sha256, facts.database_member_sha256) == (
        "verified_v1", independent, inner["contents"][0]["sha256"],
    )
    assert validate_projection_verification(inner, outer_manifest=outer_for_inner(inner)) == facts
    with pytest.raises(AttributeError):
        facts.mode = "legacy_unverified"
    assert canonical_digest({"text": "é"}) == hashlib.sha256(b'{"text":"\xc3\xa9"}').hexdigest()


@pytest.mark.parametrize("version", [None, 0, 2, True, 1.0, "1"])
def test_unknown_or_coerced_proof_version_refuses(version):
    inner = protocol_record()
    inner["projection_verification"]["version"] = version
    rehash(inner["projection_verification"])
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_record(inner)


@pytest.mark.parametrize("case", [
    "missing_field", "extra_field", "noncanonical_capture", "zero_owner", "boolean_owner",
    "uppercase_hash", "short_hash", "stale_hash", "missing_count_label", "extra_count_label",
    "negative_count", "boolean_count", "scratch_digest", "restored_digest",
])
def test_exact_shape_identity_counts_and_boundary_digest_claims_refuse(case):
    inner = protocol_record()
    proof = inner["projection_verification"]
    if case == "missing_field":
        proof.pop("bootstrap_sha256")
    elif case == "extra_field":
        proof["verified"] = True
    elif case == "noncanonical_capture":
        proof["capture_id"] = proof["capture_id"].upper()
    elif case in {"zero_owner", "boolean_owner"}:
        proof["source_makerspace_id"] = 0 if case == "zero_owner" else True
    elif case in {"uppercase_hash", "short_hash"}:
        proof["bootstrap_sha256"] = "A" * 64 if case == "uppercase_hash" else "a" * 63
    elif case == "stale_hash":
        proof["bootstrap_sha256"] = "0" * 64
    elif case == "missing_count_label":
        proof["row_counts"].pop("inventory.Category")
    elif case == "extra_count_label":
        proof["row_counts"]["unknown.Table"] = 0
    elif case in {"negative_count", "boolean_count"}:
        proof["row_counts"]["inventory.Category"] = -1 if case == "negative_count" else False
    else:
        proof["scratch_projected_sha256" if case == "scratch_digest" else "restored_projected_sha256"] = "0" * 64
    if case != "stale_hash":
        rehash(proof)
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_record(inner)


@pytest.mark.parametrize("section,field,value", [
    ("root", "capture_id", "668267be-8127-4da6-810d-d3c2b90c6fc0"),
    ("source", "makerspace_id", 8),
    ("source", "catalog_digest", "0" * 64),
    ("source", "encryption_mode", True),
    ("lineage", "database_image_sha256", "0" * 64),
    ("lineage", "derivation_policy_sha256", "0" * 64),
    ("database", "mapped_raw_sha256", "0" * 64),
    ("database", "member_path", "other.dump"),
    ("user_closure", "sha256", "0" * 64),
])
def test_inner_source_capture_catalog_policy_raw_and_closure_bindings(section, field, value):
    inner = protocol_record()
    (inner if section == "root" else inner[section])[field] = value
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_record(inner)


def test_policy_digest_cannot_be_redefined_even_with_matching_lineage_and_proof_hash():
    inner = protocol_record()
    proof = inner["projection_verification"]
    proof["derivation_policy_sha256"] = inner["lineage"]["derivation_policy_sha256"] = "0" * 64
    rehash(proof)
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_record(inner)


@pytest.mark.parametrize("case", ["missing", "duplicate", "wrong_sha", "zero_size", "boolean_size", "absent"])
def test_exact_database_dump_member_binding_refuses(case):
    inner = protocol_record()
    member = inner["contents"][0]
    if case == "missing":
        inner["contents"] = []
    elif case == "duplicate":
        inner["contents"].append(deepcopy(member))
    else:
        field, value = {"wrong_sha": ("sha256", "0" * 64), "zero_size": ("size", 0),
                        "boolean_size": ("size", True), "absent": ("present", False)}[case]
        member[field] = value
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_record(inner)


@pytest.mark.parametrize("case", ["duplicate", "unsorted", "unknown_location", "wrong_disposition", "extra_field", "bad_pk", "digest"])
def test_semantic_records_require_exact_locations_order_uniqueness_and_digest(case):
    inner = protocol_record()
    proof = inner["projection_verification"]
    records = [semantic_record(1), semantic_record(2)]
    if case == "duplicate":
        records[1] = deepcopy(records[0])
    elif case == "unsorted":
        records.reverse()
    elif case == "unknown_location":
        records[0]["location"] = "json:unreviewed_user_data"
    elif case == "wrong_disposition":
        records[0]["disposition"] = "reset"
    elif case == "extra_field":
        records[0]["value"] = {"raw_foreign_contact": "must never travel"}
    elif case == "bad_pk":
        records[0]["source_row_pk"] = True
    proof["semantic_references"] = records
    proof["semantic_references_sha256"] = canonical_digest([] if case == "digest" else records)
    rehash(proof)
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_record(inner)


def test_valid_sorted_semantic_record_is_accepted_without_target_lookup():
    inner = protocol_record()
    proof = inner["projection_verification"]
    proof["semantic_references"] = [semantic_record(1), semantic_record(2)]
    proof["semantic_references_sha256"] = canonical_digest(proof["semantic_references"])
    rehash(proof)
    assert validate_projection_record(inner).mode == "verified_v1"


def test_syntactically_valid_changed_loss_ledger_cannot_match_the_original_proof():
    inner = protocol_record()
    inner["cross_tenant_lost_edges"] = [dict(model_label="events.EventCollaborator", source_row_pk=17,
                                            field_name="event", reason_code="foreign_collaborator_dropped")]
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_record(inner)


@pytest.mark.parametrize("version", [None, 0, 3, True, "1"])
def test_unknown_outer_version_never_selects_legacy(version):
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_verification({}, outer_manifest=dict(format="spaceworks-tenant-dump-v1", version=version))


def test_actual_v1_context_returns_explicitly_weaker_facts_without_synthesizing_proof():
    facts = validate_projection_verification({}, outer_manifest=dict(format="spaceworks-tenant-dump-v1", version=1))
    assert (facts.mode, facts.proof_sha256, facts.database_member_sha256) == ("legacy_unverified", None, None)
    # Producer helper has no outer context and must always demand the stronger record.
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_record({})


@pytest.mark.parametrize("attempt", ["missing", "unknown_proof", "legacy_boolean"])
def test_v2_cannot_downgrade_to_legacy(attempt):
    inner = protocol_record()
    outer = outer_for_inner(inner)
    if attempt == "unknown_proof":
        inner["projection_verification"]["version"] = 99
    else:
        inner.pop("projection_verification")
        if attempt == "legacy_boolean":
            inner.update(legacy_unverified=True, projection_verified=False, outer_version=1)
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_verification(inner, outer_manifest=outer)


@pytest.mark.parametrize("field,value", [
    ("catalog_sha256", "0" * 64), ("derivation_policy_sha256", "0" * 64),
    ("content_ledger_sha256", "0" * 64), ("content_ledger_count", 2),
])
def test_authenticated_v2_outer_bindings_are_consumed(field, value):
    inner = protocol_record()
    outer = outer_for_inner(inner)
    outer["compatibility"][field] = value
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_verification(inner, outer_manifest=outer)
