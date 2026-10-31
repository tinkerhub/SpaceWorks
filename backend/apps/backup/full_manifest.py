"""Separate Ed25519 domain over the full manifest and every payload member."""

import base64
import json

from apps.backup.errors import BackupBuildError
from apps.backup.full_format import FULL_FORMAT, FULL_PROTOCOL, FULL_SIGNATURE_DOMAIN
from apps.backup.full_manifest_validation import validate_full_manifest
from apps.backup.main_projection_registry import OMITTED_OPERATIONAL_MODELS
from apps.backup.outer_manifest import _canonical_json, _private_key, _public_key
from apps.backup.outer_manifest_facts import digest_json
from apps.backup.outer_manifest_validation import component_id
from apps.backup.recipients import fingerprint_for
from apps.ed25519 import Ed25519Error, fingerprint_public_key, sign_bytes, verify_bytes


def full_source_digest(source):
    return digest_json({"format": FULL_FORMAT, "source_capture": source})


def build_full_manifest(capture, detailed):
    frozen = capture.promotion_snapshot()
    if (
        detailed["covered_makerspace_ids"] != [item["makerspace_id"] for item in frozen["retained"]]
        or detailed["backup_run_id"] != (frozen["run"]["id"] if frozen["run"] else None)
    ):
        raise BackupBuildError("The full manifest population or run differs from its frozen capture.")
    dump = next(item for item in detailed["contents"] if item["path"] == "database.dump")
    if dump["sha256"] != frozen["source_dump_sha256"]:
        raise BackupBuildError("The full source dump differs from its frozen capture.")
    fingerprints = sorted({
        fingerprint_for(item["public_recipient"])
        for item in capture._kwargs["platform_recipients"]
    })
    source = {
        "capture_id": frozen["capture_id"],
        "database_identity": frozen["source_database_identity"],
        "server_identity": frozen["source_server_identity"],
        "dump_sha256": frozen["source_dump_sha256"],
        "object_ownership_digest": frozen["object_ownership_digest"],
    }
    # Match the existing JSON writer for provider timestamp header values.
    manifest = json.loads(json.dumps(detailed, default=str))
    manifest.pop("recipients", None)
    manifest.update({
        "format": FULL_FORMAT, "protocol_version": FULL_PROTOCOL,
        "artifact_id": str(capture.archive.pk), "capture_id": str(capture.capture_id),
        "source_capture": source, "source_timestamp": detailed["snapshot_at"],
        "custody_mode": "full-platform-readable",
        "omitted_operational_models": sorted(OMITTED_OPERATIONAL_MODELS),
        "build_identity": {"build": detailed["build"], "oci_digest": detailed["oci_digest"]},
        "makerspace_sets": {
            "retained": detailed["covered_makerspace_ids"],
            "readable_main": detailed["covered_makerspace_ids"], "sovereign": [],
        },
        "main_component": {
            "component_id": component_id(capture.capture_id, "main"), "kind": "main",
            "path": "database.dump", "size_bytes": dump["size"],
            "ciphertext_sha256": dump["sha256"], "recipient_fingerprints": fingerprints,
            "semantic_digest": full_source_digest(source),
        },
        "recipient_fingerprints": fingerprints, "slices": [], "slice_components": [],
        "user_closure_digest": frozen["user_closure_digest"],
    })
    validate_full_manifest(manifest)
    try:
        signature = sign_bytes(_signature_payload(manifest), _private_key())
        public = _public_key()
        verify_bytes(_signature_payload(manifest), signature, public)
    except Ed25519Error as exc:
        raise BackupBuildError("The full archive signing identity is invalid.") from exc
    manifest["archive_signature"] = {
        "algorithm": "ed25519", "signer_fingerprint": fingerprint_public_key(public),
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return manifest


def verify_full_manifest(manifest):
    unsigned = dict(manifest)
    signature = unsigned.pop("archive_signature", None)
    validate_full_manifest(unsigned)
    if (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "signer_fingerprint", "value"}
        or signature["algorithm"] != "ed25519"
    ):
        raise BackupBuildError("The full archive signature is malformed.")
    public = _public_key()
    if signature["signer_fingerprint"] != fingerprint_public_key(public):
        raise BackupBuildError("The host archive verification key does not match the manifest signer.")
    try:
        raw = base64.b64decode(signature["value"], validate=True)
        verify_bytes(_signature_payload(unsigned), raw, public)
    except (Ed25519Error, ValueError, TypeError) as exc:
        raise BackupBuildError("The full archive signature is invalid.") from exc
    return True


def _signature_payload(unsigned):
    manifest = _canonical_json(unsigned)
    ledger = _canonical_json(unsigned["contents"])
    return (
        FULL_SIGNATURE_DOMAIN + len(manifest).to_bytes(8, "big") + manifest
        + len(ledger).to_bytes(8, "big") + ledger
    )
