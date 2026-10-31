"""Real signed envelopes for validator tests; payload bytes are deliberately synthetic.

These fixtures are not pg_dump/age restore evidence. The roundtrip module owns that.
No validator, schema registry or cryptographic check is patched here.
"""

import base64
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import uuid

from apps.backup.archive_metadata import settings_manifest
from apps.backup.archive_payload import CONTINUITY_KEYS
from apps.backup.full_manifest import _signature_payload, build_full_manifest
from apps.backup.outer_manifest import _private_key, _public_key
from apps.backup.outer_manifest_facts import closure_digest_from_slice_ledgers
from apps.ed25519 import fingerprint_public_key, sign_bytes


BUILD = {
    "source_hash": "a" * 64, "git_sha": "b" * 40,
    "git_describe": "stage3-fixture", "built_at": "2026-10-29T00:00:00+00:00",
}
OCI = "sha256:" + "c" * 64
STAMP = "2026-10-29T00:00:00+00:00"
PLATFORM = "age1stage3-envelope-fixture"


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def sign_manifest(manifest, *, domain=None):
    """Permit intentionally signed invalid structures to exercise the closed schema."""
    unsigned = deepcopy(manifest)
    unsigned.pop("archive_signature", None)
    payload = _signature_payload(unsigned)
    if domain is not None:
        from apps.backup.full_format import FULL_SIGNATURE_DOMAIN

        payload = domain + payload[len(FULL_SIGNATURE_DOMAIN):]
    public = _public_key()
    unsigned["archive_signature"] = {
        "algorithm": "ed25519", "signer_fingerprint": fingerprint_public_key(public),
        "value": base64.b64encode(sign_bytes(payload, _private_key())).decode("ascii"),
    }
    return unsigned


@dataclass
class FullFixture:
    root: Path
    manifest: dict
    members: dict
    secrets: dict
    encrypted: Path
    bundle: Path

    @property
    def manifest_file(self):
        return self.root / "manifest.json"

    @property
    def secrets_file(self):
        return self.root / "keys/env.json"

    def write(self):
        for name, payload in self.members.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self.manifest_file.write_text(json.dumps(self.manifest, sort_keys=True))
        self.write_tar()

    def write_tar(self, *, extra=(), omit=(), replacements=None):
        payloads = {**self.members, "manifest.json": self.manifest_file.read_bytes()}
        payloads.update(replacements or {})
        with tarfile.open(self.bundle, "w") as archive:
            for name, payload in payloads.items():
                if name in omit:
                    continue
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            for info, payload in extra:
                archive.addfile(info, io.BytesIO(payload) if payload is not None else None)

    def kwargs(self):
        return {
            "encrypted_file": self.encrypted, "bundle": self.bundle,
            "manifest_file": self.manifest_file,
            "continuity_secrets_file": self.secrets_file,
            "expected_sha256": sha(self.encrypted.read_bytes()),
        }


def make_full_fixture(tmp_path, *, archive_id=None, frozen=None, include_objects=True):
    root = tmp_path / "full-root"
    root.mkdir()
    archive_id = archive_id or uuid.uuid4()
    secrets = {name: "fixture-continuity-" + name for name in CONTINUITY_KEYS}
    members = {
        "database.dump": b"synthetic dump: no restore claim",
        "keys/env.json": json.dumps(secrets, sort_keys=True).encode(),
        "objects/private/evidence/issue.jpg": b"private evidence bytes",
        "objects/public_image/inventory/tool.png": b"public image bytes",
    }
    if not include_objects:
        members = {name: payload for name, payload in members.items() if not name.startswith("objects/")}
    contents = [
        {"path": name, "size": len(payload), "sha256": sha(payload)}
        for name, payload in sorted(members.items())
    ]
    if frozen is None:
        frozen = {
            "capture_id": str(uuid.uuid4()), "retained": [], "run": None,
            "source_database_identity": "stage3_source",
            "source_server_identity": {
                "server_version_num": "160004", "database_uuid": str(uuid.uuid4()),
                "system_identifier": None,
                "endpoint": {"host": "source-db", "port": 5432,
                             "database": "stage3_source", "tls_identity": ""},
            },
            "source_dump_sha256": sha(members["database.dump"]),
            "object_ownership_digest": "d" * 64,
            "user_closure_digest": closure_digest_from_slice_ledgers(()),
        }
    else:
        frozen = deepcopy(frozen)
        assert frozen["source_dump_sha256"] == sha(members["database.dump"])
    objects = []
    for name, payload in members.items():
        if not name.startswith("objects/"):
            continue
        _, bucket, key = name.split("/", 2)
        objects.append({
            "bucket_kind": bucket, "canonical_component": "main", "makerspace_id": None,
            "module_key": "inventory", "key": key, "version_id": "v1",
            "size": len(payload), "sha256": sha(payload), "metadata": {"test": "full"},
            "content_type": "application/octet-stream", "headers": {},
        })
    setting_facts = settings_manifest()
    for name, value in secrets.items():
        setting_facts[name]["fingerprint"] = sha(value.encode())
    detailed = {
        "archive_id": str(archive_id), "backup_run_id": frozen["run"]["id"] if frozen["run"] else None,
        "scope": "deployment", "makerspace_id": None, "age_encrypted": True,
        "snapshot_at": STAMP, "build": dict(BUILD), "oci_digest": OCI,
        "covered_makerspace_ids": [item["makerspace_id"] for item in frozen["retained"]],
        "excluded_makerspace_ids": [], "partial": False, "purge_warning": "Retained copies remain.",
        "contents": contents, "settings": setting_facts,
        "storage": {"consistency": {"private": "versioned", "public_image": "versioned"}, "objects": objects},
        "postgres": {"source_server_major": 16, "client": "pg_dump (PostgreSQL) 16.4",
                     "supported_source_majors": [14, 15, 16, 17]},
    }
    capture = SimpleNamespace(
        archive=SimpleNamespace(pk=archive_id), capture_id=uuid.UUID(frozen["capture_id"]),
        promotion_snapshot=lambda: deepcopy(frozen),
        _kwargs={"platform_recipients": [{"public_recipient": PLATFORM}]},
    )
    manifest = build_full_manifest(capture, detailed)
    encrypted = tmp_path / "synthetic.tar.age"
    encrypted.write_bytes(b"synthetic encrypted artifact for admission tests only")
    fixture = FullFixture(root, manifest, members, secrets, encrypted, tmp_path / "full.tar")
    fixture.write()
    return fixture
