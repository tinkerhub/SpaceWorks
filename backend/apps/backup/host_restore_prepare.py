"""Read-only archive admission and sealed inputs before target quiescence."""

import json
import os
from pathlib import Path
import re
import uuid

from .full_format import FULL_FORMAT, FULL_PROTOCOL
from .host_restore_configuration import digest, json_digest
from .host_restore_files import delegate_file, delegate_tree, extract_bundle, project_metadata, public_json, seal_file
from .host_restore_transport import RestoreHostError, private_json, trusted


LEGACY_FORMATS = {"spaceworks-phase5a-v1", "spaceworks-phase5a-v2", "spaceworks-phase5a-v3"}


def route_facts(manifest):
    kind = manifest.get("format")
    return {"archive_scope": manifest.get("scope"), "archive_format": kind,
        "archive_protocol_version": (manifest["protocol_version"] or None) if "protocol_version" in manifest else "",
        "archive_partial": manifest.get("partial", False if kind in {
            "spaceworks-phase5a-v1", "spaceworks-phase5a-v2"} else None)}


def require_route(facts):
    kind = facts.get("archive_format")
    if (facts.get("archive_scope") != "deployment" or facts.get("archive_partial") is not False
            or not ((kind == FULL_FORMAT and facts.get("archive_protocol_version") == FULL_PROTOCOL)
                    or (kind in LEGACY_FORMATS and facts.get("archive_protocol_version") == ""))):
        raise RestoreHostError("Only complete signed-full or registered same-host historical routes are supported.")
    return kind


class RestoreInputs:
    def __init__(self, transport, *, restore_id=None, source=None, username=None, expected=None):
        self.transport = transport
        token = restore_id or str(uuid.uuid4())
        self.private = transport.ops / "private" / f"inplace-{token}"
        self.private.parent.mkdir(mode=0o700, exist_ok=True)
        trusted(self.private.parent, private=True, directory=True)
        self.private.mkdir(mode=0o700)
        from .host_private_file import _fsync_directory
        _fsync_directory(self.private.parent)
        _fsync_directory(transport.ops)
        print(f"Private restore evidence retained at {self.private}.", flush=True)
        self.work = transport.ops / "work" / f"inplace-{token}"
        self.work.mkdir(mode=0o700)
        os.chown(self.work, 10001, 10001)
        self.public = transport.host / "public" / f"inplace-{token}"
        self.public.mkdir(mode=0o750)
        os.chown(self.public, 0, 10001)
        self.public_app = "/run/spaceworks-host/" + self.public.name
        _fsync_directory(self.public.parent)
        _fsync_directory(self.work.parent)
        self.restore_id = restore_id
        self.prospective = None
        self.control_record = None
        self.metadata = None
        if not source:
            # Stored identity selects the route before export, decryption or parsing.
            self.metadata = self.describe()
            self.kind = require_route(self.metadata)
        if source:
            self.outer_sha256 = seal_file(source, self.private / "archive.tar.age")
            if expected and expected != self.outer_sha256:
                raise RestoreHostError("The pinned encrypted artifact hash differs.")
        else:
            transport.control("export-archive", restore_id, "--output", transport.app_path(self.work / "archive.tar.age"))
            self.outer_sha256 = seal_file(self.work / "archive.tar.age", self.private / "archive.tar.age")
            if self.outer_sha256 != self.metadata["archive_sha256"]:
                raise RestoreHostError("The sealed encrypted artifact differs from the registered outer hash.")
        delegate_file(self.private / "archive.tar.age", self.public / "archive.tar.age")
        identity = transport.ops / "work/age-identity.txt"
        if os.environ.get("BACKUP_AGE_IDENTITY_FILE") not in {None, "", str(identity)}:
            raise RestoreHostError("Age identity path overrides are unsupported by this bounded transport.")
        # Decryption uses the installed image dependency, never a host Python package.
        transport.compose("exec", "-T", "backend", "age", "-d", "-i", transport.app_path(identity),
            "-o", transport.app_path(self.work / "archive.tar"), self.public_app + "/archive.tar.age")
        seal_file(self.work / "archive.tar", self.private / "archive.tar")
        project_metadata(self.private / "archive.tar", self.private / "metadata")
        self.manifest = json.loads((self.private / "metadata/manifest.json").read_bytes())
        self.continuity = json.loads((self.private / "metadata/keys/env.json").read_bytes())
        if not isinstance(self.manifest, dict) or self.manifest.get("age_encrypted") is not True:
            raise RestoreHostError("The bounded deployment manifest is invalid.")
        facts = route_facts(self.manifest)
        require_route(facts)
        if source:
            self.kind = facts["archive_format"]
            if self.kind != FULL_FORMAT:
                raise RestoreHostError("Cross-host import requires an externally pinned signed-full archive.")
        else:
            self.match_registered(facts)
        delegate_file(self.private / "archive.tar", self.public / "archive.tar")
        delegate_tree(self.private / "metadata", self.public / "metadata")
        if self.kind == FULL_FORMAT:
            if source or self.metadata["kind"] == "disaster":
                # Non-reset rollback always compares against installed keys.
                self.delegate_prospective()
            args = self.import_arguments()
            if self.prospective and self.restore_id:
                args += ["--restore-id", self.restore_id]
            result = transport.compose("run", "--rm", "--no-deps", "-T", "backend", "--role", "management",
                "python", "manage.py", "preflight_backup_import", *args)
            if result.splitlines()[-1] != "import-preflight-ok":
                raise RestoreHostError("Static signed-full import admission did not complete.")
        # FULL has now passed external-pinned signature and the complete tar ledger;
        # historical input is authenticated by its pre-existing stored outer hash.
        extract_bundle(self.private / "archive.tar", self.private / "bundle")
        for name in ("manifest.json", "keys/env.json"):
            if (self.private / "bundle" / name).read_bytes() != (self.private / "metadata" / name).read_bytes():
                raise RestoreHostError("Extracted metadata differs from the admitted projection.")
        from .restore_manifest_facts import validate_restore_object_facts
        validate_restore_object_facts(self.manifest, self.private / "bundle")
        delegate_tree(self.private / "bundle", self.public / "bundle")
        if source:
            # Registration still runs under the coherent OLD installed keys.
            args = self.import_arguments()
            identifier = transport.compose("run", "--rm", "--no-deps", "-T", "backend", "--role", "management",
                "python", "manage.py", "import_backup_archive", "--username", username, *args).splitlines()[-1]
            self.restore_id = str(uuid.UUID(identifier))
            self.metadata = self.describe()
            self.match_registered(facts)
            self.delegate_prospective()
        private_json(self.private / "input.json", {"restore_id": self.restore_id,
            "archive_sha256": self.outer_sha256, "public": str(self.public), "work": str(self.work),
            "manifest_sha256": json_digest(self.manifest), "metadata": self.metadata})

    def describe(self):
        metadata = json.loads(self.transport.control("describe", self.restore_id).splitlines()[-1])
        if (metadata.get("restore_id") != self.restore_id
                or str(uuid.UUID(metadata["archive_id"])) != metadata["archive_id"]
                or not re.fullmatch(r"[0-9a-f]{64}", metadata.get("archive_sha256") or "")
                or type(metadata.get("requested_by")) is not int or metadata["requested_by"] <= 0
                or metadata.get("kind") not in {"disaster", "rollback_in_place"}):
            raise RestoreHostError("The registered restore identity or stored outer hash is invalid.")
        require_route(metadata)
        return metadata

    def match_registered(self, facts):
        if (any(self.metadata.get(key) != value for key, value in facts.items())
                or self.manifest.get("archive_id") != self.metadata["archive_id"]
                or self.metadata["archive_sha256"] != self.outer_sha256):
            raise RestoreHostError("The bounded manifest differs from the registered archive route and identity.")

    def delegate_prospective(self):
        payload = {"schema": "spaceworks-restore-prospective-v1", "archive_sha256": self.outer_sha256,
            "manifest_sha256": json_digest(self.manifest),
            "continuity_sha256": digest((self.private / "metadata/keys/env.json").read_bytes())}
        if self.restore_id:
            payload["restore_id"] = self.restore_id
        name = f"restore-prospective-{self.outer_sha256}.json"
        public_json(self.transport.host / "public" / name, payload)
        self.prospective = "/run/spaceworks-host/" + name

    def import_arguments(self):
        args = ["--encrypted-file", self.public_app + "/archive.tar.age", "--bundle", self.public_app + "/archive.tar",
            "--manifest", self.public_app + "/metadata/manifest.json", "--continuity-secrets",
            self.public_app + "/metadata/keys/env.json", "--expected-sha256", self.outer_sha256]
        if self.prospective:
            args += ["--prospective-record", self.prospective]
        return args

    def preflight(self, digest_value, *, prospective=False):
        args = ["preflight", self.restore_id, "--manifest", self.public_app + "/bundle/manifest.json",
            "--bundle", self.public_app + "/bundle", "--encrypted-file", self.public_app + "/archive.tar.age",
            "--decrypted-bundle", self.public_app + "/archive.tar", "--continuity-secrets",
            self.public_app + "/bundle/keys/env.json", "--current-oci-digest", digest_value]
        if prospective and self.prospective:
            args += ["--prospective-record", self.prospective]
        expected = "full-preflight-ok" if self.kind == FULL_FORMAT else "preflight-ok"
        if self.transport.control(*args).splitlines()[-1] != expected:
            raise RestoreHostError("The authenticated restore path changed during preflight.")

    def export_control(self, decision):
        output = self.work / "restore-control.json"
        self.transport.control("export-control", self.restore_id, "--output", self.transport.app_path(output),
                               "--decision", decision)
        seal_file(output, self.private / "restore-control.json")
        self.control_record = json.loads((self.private / "restore-control.json").read_bytes())
        delegate_file(self.private / "restore-control.json", self.public / "restore-control.json")
        return self.control_record
