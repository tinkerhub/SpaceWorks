"""Canonical selected files for X12; opaque framing here never claims age coverage."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tarfile

from apps.tenant_migration.tenant_client_catalog import _canonical, _digest, classify_entry
from apps.tenant_migration.tenant_dump_outer_artifact import write_outer_artifact
from apps.tenant_migration.tenant_dump_outer_manifest import build_outer_manifest
from apps.tenant_migration.tenant_restore_types import ArtifactPreflight, RestoreInputs
from tests.tenant_migration.x13_proof_helpers import (
    CAPTURE, DEPLOYMENT, complete_admission_inner, protocol_record, rehash,
)

DUMP = b"X12 selected database bytes\n"
PAYLOAD = b"opaque framing only; real age producer tests are separate\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def catalog_entry(**changes):
    entry = dict(source_client_ref="1" * 64, label="Source kiosk", client_type="browser",
                 rate_limit_tier="standard", is_active=True, stored_scopes=["public:read"],
                 stored_origins=["https://source.example.test"])
    entry.update(changes)
    entry.update(classify_entry(entry))
    entry["source_entry_sha256"] = _digest(entry)
    return entry


def catalog(*entries, capture=CAPTURE, owner=7):
    entries = sorted(deepcopy(entries), key=lambda entry: entry["source_client_ref"])
    return dict(version=1, capture_id=capture, source_deployment_id=DEPLOYMENT,
                source_makerspace_id=owner, entries=entries, sha256=_digest(entries))


def admission_inner(capture=CAPTURE, *, dump=DUMP, clients=None):
    inner = complete_admission_inner(protocol_record())
    inner["capture_id"] = capture
    proof = inner["projection_verification"]
    proof.update(capture_id=capture, database_member_sha256=sha(dump))
    rehash(proof)
    inner["contents"][0].update(size=len(dump), sha256=sha(dump))
    inner["api_client_catalog"] = clients if clients is not None else catalog(capture=capture)
    return inner


def outer_manifest(inner, *, version=2, data=None, payload=PAYLOAD):
    data = data if data is not None else _canonical(inner).encode()
    compatibility = {} if version == 1 else dict(
        inner_manifest_sha256=sha(data), catalog_sha256=inner["source"]["catalog_digest"],
        derivation_policy_sha256=inner["lineage"]["derivation_policy_sha256"],
        content_ledger_sha256=_digest(inner["contents"]), content_ledger_count=len(inner["contents"]),
        source_pii_mode="plaintext",
    )
    return build_outer_manifest(
        format=inner["format"], version=version, artifact_id=inner["capture_id"],
        capture_id=inner["capture_id"], outer_recipient_fingerprints=["fixture-recipient"],
        tenant_dek_recipient_fingerprints=["fixture-recipient"],
        encrypted_members=[dict(path="payload.age", size=len(payload), sha256=sha(payload))],
        source_build=dict(source_hash="x12-framing-fixture"), postgres_major=16,
        compatibility=compatibility,
    )


def wrapper_bytes(manifest, payload=PAYLOAD):
    """Independent expected canonical USTAR bytes, also permits malformed manifests."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in (("outer-manifest.json", _canonical(manifest).encode()), ("payload.age", payload)):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o600
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def private_write(path, data):
    path = Path(path)
    path.write_bytes(data)
    path.chmod(0o600)
    return path


class SelectedArtifact:
    def __init__(self, root, *, inner=None, version=2, data=None, dump=DUMP):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.inner = deepcopy(inner if inner is not None else admission_inner(dump=dump))
        self.data = data if data is not None else _canonical(self.inner).encode()
        self.inner_path = private_write(self.root / "manifest.json", self.data)
        self.dump_path = private_write(self.root / "database.dump", dump)
        payload = private_write(self.root / "payload.age", PAYLOAD)
        self.outer = outer_manifest(self.inner, version=version, data=self.data)
        self.path = self.root / "selected.tar"
        if not self.path.exists():
            write_outer_artifact(payload, self.path, self.outer)
        assert self.path.read_bytes() == wrapper_bytes(self.outer)
        self.inputs = RestoreInputs(CAPTURE, sha(self.path.read_bytes()), self.inner["capture_id"],
                                    "operator@example.test")
        self.reads = []

    def selected_artifact_path(self, inputs):
        self.reads.append("selected")
        return self.path

    def inner_manifest_path(self, inputs):
        self.reads.append("inner")
        return self.inner_path

    def database_dump_path(self):
        self.reads.append("dump")
        return self.dump_path

    def static_preflight(self, inputs):
        return ArtifactPreflight(*([True] * 12))

    def replace_outer(self, mutate):
        mutate(self.outer)
        private_write(self.path, wrapper_bytes(self.outer))
        self.inputs = replace(self.inputs, artifact_sha256=sha(self.path.read_bytes()))


def approvals_for(artifact, *, now=None):
    from datetime import datetime, timedelta, timezone

    now = now or datetime.now(timezone.utc)
    source = artifact.inner["api_client_catalog"]
    records = []
    for index, entry in enumerate(source["entries"]):
        record = dict(
            artifact_sha256=artifact.inputs.artifact_sha256, capture_id=artifact.inputs.capture_id,
            source_catalog_sha256=source["sha256"], source_client_ref=entry["source_client_ref"],
            source_entry_sha256=entry["source_entry_sha256"], label=entry["label"],
            client_type=entry["client_type"], rate_limit_tier=entry["rate_limit_tier"],
            target_scopes=entry["canonical_scopes"], target_origins=["https://target.example.test"],
            privileged_scopes_approved=False, host_principal="x12-host-operator",
            approved_at=(now - timedelta(minutes=1)).isoformat(),
            expires_at=(now + timedelta(hours=1)).isoformat(), nonce=f"x12-nonce-{index}",
        )
        record["approval_record_sha256"] = _digest(record)
        records.append(record)
    return dict(version=1, approvals=records)


def rehash_approval(record):
    record["approval_record_sha256"] = _digest({
        key: value for key, value in record.items() if key != "approval_record_sha256"
    })
