"""Small honest protocol records; builder integration supplies real dump proofs."""

from copy import deepcopy
import json
from types import SimpleNamespace

from apps.tenant_migration.tenant_dump_projection_proof import (
    FORMAT, build_projection_record, canonical_digest,
)
from apps.tenant_migration.tenant_dump_projection_schema import PROJECTED_LABELS

CAPTURE = "568267be-8127-4da6-810d-d3c2b90c6fc0"
DEPLOYMENT = "ed007343-a6ac-477a-9d20-88ce88d24313"


def rehash(proof):
    proof["sha256"] = canonical_digest({key: value for key, value in proof.items() if key != "sha256"})


def inner_for_proof(proof, closure, *, size=123):
    """Only the fields the projection-proof validator owns, with explicit bindings."""
    return dict(
        format=FORMAT, capture_id=proof["capture_id"],
        source=dict(makerspace_id=proof["source_makerspace_id"],
                    catalog_digest=proof["catalog_sha256"], encryption_mode=False),
        lineage=dict(database_image_sha256=proof["source_database_image_sha256"],
                     derivation_policy_sha256=proof["derivation_policy_sha256"]),
        database=dict(member_path="database.dump", mapped_raw_sha256=proof["mapped_raw_sha256"]),
        contents=[dict(path="database.dump", sha256=proof["database_member_sha256"], size=size, present=True)],
        user_closure=deepcopy(closure), cross_tenant_lost_edges=[], projection_verification=deepcopy(proof),
    )


def protocol_record():
    """Zero-row universe is a structure fixture, never a claimed builder result."""
    closure = dict(included=[], stubbed=[], refused=[])
    closure["sha256"] = canonical_digest(closure)
    catalog = canonical_digest("reviewed fixture catalog")
    expectations = SimpleNamespace(
        capture_id=CAPTURE, source_makerspace_id=7,
        source_database_image_sha256=canonical_digest("fixture source image"), catalog_sha256=catalog,
        derivation_policy_sha256=canonical_digest(dict(
            format=FORMAT, policy_version=6, catalog_digest=catalog,
            source_encryption_mode=False, companion_slice=False,
        )),
        expected_cross_tenant_lost_edges=(), expected_semantic_references=(),
        user_closure_sha256=closure["sha256"],
    )
    raw = canonical_digest("fixture projected content")
    proof = build_projection_record(
        expectations, database_member_sha256=canonical_digest(b"fixture dump".hex()),
        row_counts={label: 0 for label in sorted(PROJECTED_LABELS)},
        row_identity_sha256=canonical_digest({label: [] for label in sorted(PROJECTED_LABELS)}),
        bootstrap_sha256=canonical_digest("fixture bootstrap"),
        mapped_raw_sha256=canonical_digest("fixture mapped columns"),
        projected_raw_sha256=raw, scratch_projected_sha256=raw, restored_projected_sha256=raw,
    )
    return inner_for_proof(proof, closure)


def outer_for_inner(inner, *, version=2):
    proof = inner["projection_verification"]
    return dict(format=FORMAT, version=version, capture_id=inner["capture_id"], compatibility=dict(
        catalog_sha256=proof["catalog_sha256"], derivation_policy_sha256=proof["derivation_policy_sha256"],
        content_ledger_sha256=canonical_digest(inner["contents"]), content_ledger_count=len(inner["contents"]),
    ))


def selected_context(tmp_path, inner, *, version=2):
    """Real selected-file admission. Opaque payload framing is not an age drill."""
    from apps.backup.digests import sha256_file
    from apps.tenant_migration.tenant_dump_outer_artifact import write_outer_artifact
    from apps.tenant_migration.tenant_dump_outer_manifest import build_outer_manifest
    from apps.tenant_migration.tenant_restore_artifact_admission import read_selected_artifact_context
    from apps.tenant_migration.tenant_restore_types import RestoreInputs

    tmp_path.chmod(0o700)
    payload = tmp_path / "payload.age"
    payload.write_bytes(b"opaque payload bytes; crypto roundtrip belongs to identity tests")
    inner_path = tmp_path / "manifest.json"
    data = json.dumps(inner, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    inner_path.write_bytes(data)
    inner_path.chmod(0o600)
    compatibility = {} if version == 1 else dict(
        inner_manifest_sha256=sha256_file(inner_path),
        catalog_sha256=inner["source"]["catalog_digest"],
        derivation_policy_sha256=inner["lineage"]["derivation_policy_sha256"],
        content_ledger_sha256=canonical_digest(inner["contents"]), content_ledger_count=len(inner["contents"]),
        source_pii_mode="plaintext",
    )
    outer = build_outer_manifest(
        format=FORMAT, version=version, artifact_id=inner["capture_id"], capture_id=inner["capture_id"],
        outer_recipient_fingerprints=["fixture-recipient"], tenant_dek_recipient_fingerprints=["fixture-recipient"],
        encrypted_members=[dict(path="payload.age", size=payload.stat().st_size, sha256=sha256_file(payload))],
        source_build=dict(source_hash="fixture-build"), postgres_major=16, compatibility=compatibility,
    )
    artifact_path = write_outer_artifact(payload, tmp_path / "selected.tar", outer)
    inputs = RestoreInputs(run_id=CAPTURE, artifact_sha256=sha256_file(artifact_path),
                           capture_id=inner["capture_id"], superadmin_email="operator@example.test",
                           detail={"outer_version": 1, "legacy_unverified": True})
    adapter = SimpleNamespace(selected_artifact_path=lambda _inputs: artifact_path,
                              inner_manifest_path=lambda _inputs: inner_path)
    return read_selected_artifact_context(inputs, adapter)


def complete_admission_inner(inner):
    """Satisfy identity's current reader contract without altering shared fixtures."""
    inner = deepcopy(inner)
    inner["source"].update(postgres_major=16, deployment_identity={"deployment_id": DEPLOYMENT}, source_pii_mode="plaintext")
    inner["source_pii_mode"] = "plaintext"
    inner["lineage"]["object_ledger_sha256"] = canonical_digest([])
    inner["objects"] = []
    inner["contents"].append(dict(path="keys/tenant-deks.age", present=False))
    inner["encryption"] = dict(
        source_pii_mode="plaintext", retained_key_inventory=[],
        mapped_column_findings=dict(mapped_rows=0, mapped_values=0, empty_values=0, envelope_values=0, plaintext_values=0),
        tenant_dek_envelope=dict(path="keys/tenant-deks.age", present=False),
    )
    inner["api_client_catalog"] = dict(version=1, capture_id=inner["capture_id"],
        source_deployment_id=DEPLOYMENT,
        source_makerspace_id=inner["source"]["makerspace_id"], entries=[], sha256=canonical_digest([]))
    return inner
