"""Strict metadata proof validation; target callers authenticate selected bytes first.

Producer reconciliation is performed by the builder against two actual databases.
A target authenticates that emitted record; it cannot reconstruct erased source facts.
This reader intentionally has no Django model/settings dependency.
"""

from dataclasses import dataclass
import hashlib
import json
from uuid import UUID

from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_projection_schema import PROJECTED_LABELS, SEMANTIC_LOCATIONS, semantic_disposition
from .tenant_dump_cross_tenant_rules import LOST_EDGE_REASON_CODES

PROOF_FIELDS = frozenset({
    "version", "capture_id", "source_makerspace_id", "source_database_image_sha256",
    "catalog_sha256", "derivation_policy_sha256", "database_member_sha256", "row_counts",
    "row_identity_sha256", "bootstrap_sha256", "mapped_raw_sha256", "projected_raw_sha256",
    "cross_tenant_lost_edges_sha256", "semantic_references", "semantic_references_sha256",
    "user_closure_sha256", "scratch_projected_sha256", "restored_projected_sha256", "sha256",
})
SEMANTIC_FIELDS = frozenset({"model_label", "source_row_pk", "location", "disposition", "value_sha256"})
FORMAT = "spaceworks-tenant-dump-v1"


@dataclass(frozen=True)
class ProjectionVerificationFacts:
    mode: str
    proof_sha256: str | None
    database_member_sha256: str | None


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _capture(value):
    return isinstance(value, str) and str(UUID(value)) == value


def _positive_pk(value):
    return type(value) is int and value > 0


def _semantic_key(item):
    return item["model_label"], str(item["source_row_pk"]), item["location"]


def _validate_semantics(values):
    if not isinstance(values, list):
        raise ValueError
    for item in values:
        if (not isinstance(item, dict) or set(item) != SEMANTIC_FIELDS
                or not _positive_pk(item["source_row_pk"])
                or not isinstance(item["model_label"], str) or not isinstance(item["location"], str)
                or (item["model_label"], item["location"]) not in SEMANTIC_LOCATIONS
                or item["disposition"] != semantic_disposition(item["model_label"], item["location"])
                or not is_sha256(item["value_sha256"])):
            raise ValueError
    if values != sorted(values, key=_semantic_key) or len({_semantic_key(item) for item in values}) != len(values):
        raise ValueError


def _validate_losses(values):
    fields = {"model_label", "source_row_pk", "field_name", "reason_code"}
    if not isinstance(values, list):
        raise ValueError
    keys = []
    for item in values:
        if (not isinstance(item, dict) or set(item) != fields
                or not _positive_pk(item["source_row_pk"])
                or not all(isinstance(item[name], str) for name in ("model_label", "field_name", "reason_code"))
                or (item["model_label"], item["field_name"], item["reason_code"]) not in LOST_EDGE_REASON_CODES):
            raise ValueError
        keys.append(tuple(str(item[name]) for name in ("model_label", "source_row_pk", "field_name", "reason_code")))
    if keys != sorted(set(keys)):
        raise ValueError



def _validate_closure(value, capture_id):
    names = ("included", "stubbed", "refused")
    if (not isinstance(value, dict) or set(value) != {*names, "sha256"}
            or any(not isinstance(value[name], list) for name in names) or value["refused"]):
        raise ValueError
    pks, refs = set(), set()
    for name in names:
        ordered = []
        for item in value[name]:
            if not isinstance(item, dict) or set(item) != {
                "user_ref", "emitted_user_pk", "reason_code", "stub_schema_version", "referencing_edges"
            }:
                raise ValueError
            pk = item["emitted_user_pk"]
            if not _positive_pk(pk):
                raise ValueError
            ref = hashlib.sha256(b"lane-d-user-v1\0" + capture_id.encode() + b"\0" + str(pk).encode()).hexdigest()
            if (item["user_ref"] != ref or pk in pks or ref in refs
                    or item["reason_code"] != ("tenant_exclusive" if name == "included" else "not_tenant_exclusive")
                    or (name == "included" and item["stub_schema_version"] is not None)
                    or (name == "stubbed" and (type(item["stub_schema_version"]) is not int or item["stub_schema_version"] != 1))):
                raise ValueError
            pks.add(pk)
            refs.add(ref)
            ordered.append(ref)
            edges, keys = item["referencing_edges"], []
            if not isinstance(edges, list):
                raise ValueError
            for edge in edges:
                if (not isinstance(edge, dict) or set(edge) != {"model_label", "source_row_pk", "field_name"}
                        or not isinstance(edge["model_label"], str) or edge["model_label"] not in PROJECTED_LABELS
                        or not _positive_pk(edge["source_row_pk"])
                        or not isinstance(edge["field_name"], str) or not edge["field_name"].isidentifier()):
                    raise ValueError
                keys.append((edge["model_label"], str(edge["source_row_pk"]), edge["field_name"]))
            if keys != sorted(set(keys)):
                raise ValueError
        if ordered != sorted(ordered):
            raise ValueError
    if value["sha256"] != canonical_digest({name: value[name] for name in names}):
        raise ValueError

def validate_projection_record(inner_manifest):
    """Producer-only strict helper: absent outer context can NEVER mean legacy."""
    try:
        inner = inner_manifest
        proof = inner["projection_verification"]
        if (not isinstance(proof, dict) or set(proof) != PROOF_FIELDS
                or type(proof["version"]) is not int or proof["version"] != 1
                or not _capture(proof["capture_id"]) or not _positive_pk(proof["source_makerspace_id"])):
            raise ValueError
        if any(not is_sha256(proof[name]) for name in PROOF_FIELDS if name.endswith("sha256")):
            raise ValueError
        counts = proof["row_counts"]
        if (not isinstance(counts, dict) or set(counts) != PROJECTED_LABELS
                or any(type(value) is not int or value < 0 for value in counts.values())):
            raise ValueError
        _validate_semantics(proof["semantic_references"])
        _validate_losses(inner["cross_tenant_lost_edges"])
        closure = inner["user_closure"]
        _validate_closure(closure, proof["capture_id"])
        source, lineage, database = inner["source"], inner["lineage"], inner["database"]
        if (inner["format"] != FORMAT or inner["capture_id"] != proof["capture_id"]
                or type(source["makerspace_id"]) is not int
                or source["makerspace_id"] != proof["source_makerspace_id"]
                or source["catalog_digest"] != proof["catalog_sha256"]
                or lineage["database_image_sha256"] != proof["source_database_image_sha256"]
                or lineage["derivation_policy_sha256"] != proof["derivation_policy_sha256"]
                or database["member_path"] != "database.dump"
                or database["mapped_raw_sha256"] != proof["mapped_raw_sha256"]
                or closure["sha256"] != proof["user_closure_sha256"]):
            raise ValueError
        if type(source["encryption_mode"]) is not bool or proof["derivation_policy_sha256"] != canonical_digest({
            "format": FORMAT, "policy_version": 6, "catalog_digest": proof["catalog_sha256"],
            "source_encryption_mode": source["encryption_mode"], "companion_slice": False,
        }):
            raise ValueError
        contents = inner["contents"]
        if not isinstance(contents, list) or any(not isinstance(item, dict) for item in contents):
            raise ValueError
        members = [item for item in contents if item.get("path") == "database.dump"]
        if (len(members) != 1 or members[0].get("sha256") != proof["database_member_sha256"]
                or type(members[0].get("size")) is not int or members[0]["size"] <= 0
                or members[0].get("present", True) is not True):
            raise ValueError
        if (proof["scratch_projected_sha256"] != proof["projected_raw_sha256"]
                or proof["restored_projected_sha256"] != proof["projected_raw_sha256"]
                or proof["cross_tenant_lost_edges_sha256"] != canonical_digest(inner["cross_tenant_lost_edges"])
                or proof["semantic_references_sha256"] != canonical_digest(proof["semantic_references"])
                or proof["sha256"] != canonical_digest({key: value for key, value in proof.items() if key != "sha256"})):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise TenantDumpVerificationError("The Lane D projection verification record is invalid.") from exc
    return ProjectionVerificationFacts("verified_v1", proof["sha256"], proof["database_member_sha256"])


def validate_projection_verification(inner_manifest, *, outer_manifest):
    """Read only AFTER the pinned artifact/outer/exact inner-buffer authentication."""
    if not isinstance(outer_manifest, dict) or outer_manifest.get("format") != FORMAT:
        raise TenantDumpVerificationError("Projection verification needs an authenticated Lane D outer manifest.")
    version = outer_manifest.get("version")
    if type(version) is int and version == 1:
        return ProjectionVerificationFacts("legacy_unverified", None, None)
    if type(version) is not int or version != 2:
        raise TenantDumpVerificationError("An unknown outer version cannot select legacy verification.")
    facts = validate_projection_record(inner_manifest)
    proof = inner_manifest["projection_verification"]
    compatibility = outer_manifest.get("compatibility")
    if (outer_manifest.get("capture_id") != proof["capture_id"]
            or not isinstance(compatibility, dict)
            or compatibility.get("catalog_sha256") != proof["catalog_sha256"]
            or compatibility.get("derivation_policy_sha256") != proof["derivation_policy_sha256"]
            or compatibility.get("content_ledger_sha256") != canonical_digest(inner_manifest["contents"])
            or type(compatibility.get("content_ledger_count")) is not int
            or compatibility["content_ledger_count"] != len(inner_manifest["contents"])):
        raise TenantDumpVerificationError("The projection proof differs from its authenticated outer bindings.")
    return facts


def build_projection_record(expectations, *, database_member_sha256, row_counts,
                            row_identity_sha256, bootstrap_sha256, mapped_raw_sha256,
                            projected_raw_sha256, scratch_projected_sha256, restored_projected_sha256):
    """Called only after the two verifier returns and finished candidate byte hash."""
    record = {
        "version": 1, "capture_id": expectations.capture_id,
        "source_makerspace_id": expectations.source_makerspace_id,
        "source_database_image_sha256": expectations.source_database_image_sha256,
        "catalog_sha256": expectations.catalog_sha256,
        "derivation_policy_sha256": expectations.derivation_policy_sha256,
        "database_member_sha256": database_member_sha256, "row_counts": dict(row_counts),
        "row_identity_sha256": row_identity_sha256, "bootstrap_sha256": bootstrap_sha256,
        "mapped_raw_sha256": mapped_raw_sha256, "projected_raw_sha256": projected_raw_sha256,
        "cross_tenant_lost_edges_sha256": canonical_digest([dict(item) for item in expectations.expected_cross_tenant_lost_edges]),
        "semantic_references": [dict(item) for item in expectations.expected_semantic_references],
        "user_closure_sha256": expectations.user_closure_sha256,
        "scratch_projected_sha256": scratch_projected_sha256,
        "restored_projected_sha256": restored_projected_sha256,
    }
    record["semantic_references_sha256"] = canonical_digest(record["semantic_references"])
    record["sha256"] = canonical_digest(record)
    return record
