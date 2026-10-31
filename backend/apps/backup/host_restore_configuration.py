"""Exact old/new environment transition behind an already blocked root marker."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import uuid

from .host_private_file import write_private_file_fsynced
from .host_restore_transport import RestoreHostError, private_json, trusted
from .host_topology_record import configuration_facts, write_topology_record


CONTINUITY = frozenset({"SECRET_KEY", "API_CLIENT_ENC_KEY", "PII_MASTER_KEY",
    "PII_MASTER_KEY_PREVIOUS", "PII_SEARCH_HASH_KEY", "HMAC_SECRET", "PUSH_TOKEN_HMAC_KEY",
    "CRON_SECRET", "AUDIT_MAC_MASTER_KEY"})
CONTROLS = frozenset({"SPACEWORKS_OPS_HOST_DIR", "SPACEWORKS_HOST_STATE_DIR"})


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_digest(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def read_controls(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        match = re.match(r"^(?:export )?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line.strip())
        if match and match[1] in CONTROLS:
            if match[1] in result:
                raise RestoreHostError("Static host control is repeated.")
            parts = shlex.split(match[2], comments=True)
            if len(parts) != 1 or not parts[0].startswith("/") or "$" in parts[0]:
                raise RestoreHostError("Static host control is unsupported.")
            result[match[1]] = parts[0]
    return result


def merged_environment(old, continuity, generation):
    if continuity is not None and (set(continuity) != CONTINUITY or
        any(not isinstance(v, str) or any(c in v for c in "\r\n\x00") for v in continuity.values())):
        raise RestoreHostError("Only the exact continuity allowlist may change.")
    replacements = dict(continuity or {})
    replacements["SPACEWORKS_TASK_GENERATION"] = str(uuid.UUID(generation))
    remaining = dict(replacements)
    lines = old.decode("utf-8").splitlines()
    seen = set()
    for index, line in enumerate(lines):
        match = re.match(r"^(?:export )?([A-Za-z_][A-Za-z0-9_]*)=", line.strip())
        if match and match[1] in replacements:
            key = match[1]
            if key in seen:
                raise RestoreHostError("Continuity environment assignment is repeated.")
            seen.add(key)
            raw = remaining.pop(key)
            value = raw.replace("\\", "\\\\").replace("'", "\\'")
            lines[index] = f"{key}='{value}'"
    for key, raw in sorted(remaining.items()):
        value = raw.replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"{key}='{value}'")
    return ("\n".join(lines) + "\n").encode()


class ConfigurationTransition:
    def __init__(self, transport, private, *, continuity=None):
        self.transport, self.private = transport, Path(private)
        self.path = self.private / "configuration.json"
        if self.path.exists():
            raise RestoreHostError("Recorded configuration requires reviewed manual recovery; no retry adoption.")
        self.continuity = dict(continuity or {})
        self.old = transport.static_env.read_bytes()
        self.generation = str(uuid.uuid4())
        self.new = merged_environment(self.old, continuity, self.generation)
        write_private_file_fsynced(self.private / "environment.old", self.old)
        write_private_file_fsynced(self.private / "environment.new", self.new)
        self.records = []
        # Every installed applicable record must match OLD before any NEW replacement.
        from .host_restore_transport import LAYERS

        for layer, overlays in LAYERS.items():
            suffix = "" if layer == "none" else f"-{layer}"
            path = transport.ops / f"compose-topology{suffix}.json"
            if not path.exists():
                continue
            trusted(path)
            files = [transport.root / "docker-compose.prod.yml"] + [
                transport.root / "docker" / f"compose.{name}.yml" for name in overlays]
            old_facts = configuration_facts(topology="bundled", static_env=transport.static_env,
                                             compose_files=files)
            if json.loads(path.read_bytes()) != old_facts:
                raise RestoreHostError("An installed topology record differs from the exact OLD environment.")
            new_facts = dict(old_facts, static_environment_sha256=digest(self.new))
            self.records.append({"path": str(path), "old": old_facts, "new": new_facts})
        if str(transport.record) not in {item["path"] for item in self.records}:
            raise RestoreHostError("The selected installed topology record is absent.")
        self.facts = {"version": 1, "phase": "prepared", "generation": self.generation,
            "old_sha256": digest(self.old), "new_sha256": digest(self.new), "records": self.records}
        private_json(self.path, self.facts)
        self.configuration_sha256 = digest(self.new)
        self.topology_sha256 = json_digest([{"path": item["path"], "facts": item["new"]} for item in self.records])
        self.proposed = self._prospective_config()

    def _prospective_config(self):
        # Read-only projection uses exactly the already wrapper-validated committed
        # family. Every launch/effect continues through the wrapper's live records.
        self.transport.validate()
        args = ["compose", "--env-file", str(self.private / "environment.new"), "--env-file",
                str(self.transport.ops / "database-pointer.env")]
        for path in self.transport.files:
            args += ["-f", str(path)]
        proposed = self.transport.docker(*args, "config", "--format", "json", json_result=True)
        import copy
        candidate = copy.copy(self.transport)
        candidate.config = proposed
        from .host_restore_admission import admit_configuration
        admit_configuration(candidate)
        for role in ("backend", "worker", "beat"):
            actual = proposed["services"][role]["environment"]
            if (actual.get("SPACEWORKS_TASK_GENERATION") != self.generation
                    or any(actual.get(key) != value for key, value in self.continuity.items())):
                raise RestoreHostError("Prospective continuity cannot be represented exactly in the installed Compose environment.")
        old = copy.deepcopy(self.transport.config)
        for role, service in old["services"].items():
            actual = proposed["services"][role].get("environment", {})
            for key in set(self.continuity) | {"SPACEWORKS_TASK_GENERATION"}:
                if key in service.get("environment", {}):
                    service["environment"][key] = actual.get(key)
        if old != proposed:
            raise RestoreHostError("Proposed configuration changes more than continuity and target task generation.")
        private_json(self.private / "resolved-new.json", proposed)
        return proposed

    def install(self):
        if self.transport.static_env.read_bytes() != self.old:
            raise RestoreHostError("Installed environment changed after admission.")
        for item in self.records:
            if json.loads(Path(item["path"]).read_bytes()) != item["old"]:
                raise RestoreHostError("Installed topology changed after admission.")
        self.facts["phase"] = "replacing-environment"
        private_json(self.path, self.facts)
        # The installation root was checked protected; use the same fsync primitive.
        from .host_restore_files import install_environment

        install_environment(self.transport.static_env, self.new)
        for item in self.records:
            self.facts["phase"] = "replacing-record:" + Path(item["path"]).name
            private_json(self.path, self.facts)
            write_topology_record(item["path"], item["new"])
        self.facts["phase"] = "installed"
        private_json(self.path, self.facts)
        self.transport.facts = self.transport.validate()
        self.transport.config = self.transport.compose("config", "--format", "json", json_result=True)
        if self.transport.config != self.proposed:
            raise RestoreHostError("Installed NEW configuration differs from its admitted prospective projection.")
        return self.facts


def verify_installed_configuration(transport, private):
    record = json.loads(trusted(Path(private) / "configuration.json", private=True).read_bytes())
    new = trusted(Path(private) / "environment.new", private=True).read_bytes()
    if record["phase"] != "installed" or digest(new) != record["new_sha256"] or transport.static_env.read_bytes() != new:
        raise RestoreHostError("The installed environment is not the exact completed NEW record.")
    for item in record["records"]:
        if json.loads(trusted(item["path"]).read_bytes()) != item["new"]:
            raise RestoreHostError("The installed topology is not the exact completed NEW record.")
    transport.validate()
    return record["new_sha256"], json_digest([
        {"path": item["path"], "facts": item["new"]} for item in record["records"]])
