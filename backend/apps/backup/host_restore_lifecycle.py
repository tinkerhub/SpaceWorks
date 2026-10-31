"""Quiesced decision, durable root block, and bounded in-place SQL/object restore."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import time
import uuid

from .full_format import FULL_FORMAT
from .host_capability_journal import CapabilityJournal
from .host_marker import MarkerState, OperationIdentity, read_marker
from .host_private_file import write_private_file_fsynced
from .host_restore_admission import admit_configuration, inventory, no_database_sessions, target_identity
from .host_restore_configuration import ConfigurationTransition, json_digest, verify_installed_configuration
from .host_restore_files import delegate_file, seal_file
from .host_restore_transport import RestoreHostError, private_json, trusted
from .host_run_ledger import RunLedger
from .host_supervisor import HostMarkerTransition
from .inplace_marker import InplaceMarkerTransition, phase_binding


DUMP = 'pg_dump --format=custom --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB"'
RESTORE = 'pg_restore --exit-on-error --single-transaction --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"'


def last(value):
    return value.splitlines()[-1]


def fixed_probe(transport, restore_id=None):
    args = ["run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
            "orchestration-ready", "/app/scripts/restore_database_probe.py"]
    if restore_id:
        args.append(restore_id)
    return transport.compose(*args, json_result=True)


def marker_controller(transport, lock, ledger, private):
    transition = HostMarkerTransition(transport.host / "public/restore-marker.json",
        CapabilityJournal(transport.host / "private/capability-journal.jsonl"))
    return InplaceMarkerTransition(transition, lock, ledger,
        transport.ops / "database-pointer.env", Path(private) / "marker-operation.json")


class InplaceRestore:
    def __init__(self, transport, lock, inputs, original_identity):
        self.t, self.lock, self.i, self.identity = transport, lock, inputs, original_identity
        self.id = inputs.restore_id
        self.blocked = False
        self.writer_ids = []
        self.old_environment = transport.static_env.read_bytes()
        self.old_facts = dict(transport.facts)
        write_private_file_fsynced(inputs.private / "environment-before.env", self.old_environment)
        self.old_marker = read_marker(transport.host / "public/restore-marker.json")
        self.old_probe = fixed_probe(transport)
        private_json(inputs.private / "admission-old.json", {"resolved": transport.config, "actual": inventory(transport)})
        private_json(inputs.private / "target-before.json", self.old_probe)
        if target_identity(transport) != original_identity:
            raise RestoreHostError("Target identity changed during archive admission.")
        self.ledger = RunLedger(transport.ops / "runs" / f"{self.id}.jsonl",
            run_id=self.id, artifact_sha256=inputs.outer_sha256)
        self.ledger.path.parent.mkdir(mode=0o700, exist_ok=True)
        trusted(self.ledger.path.parent, private=True, directory=True)
        if self.ledger.path.exists():
            raise RestoreHostError("A previous operation ledger requires reviewed recovery; replay is refused.")
        self.marker = marker_controller(transport, lock, self.ledger, inputs.private)

    def decision(self):
        t, i = self.t, self.i
        digest_value = admit_configuration(t)
        i.preflight(digest_value, prospective=True)
        if last(t.control("claim", self.id)) not in {"claimed", "resume"}:
            raise RestoreHostError("The intent is not an admitted pre-effect operation.")
        i.preflight(digest_value, prospective=True)
        inventory(t)
        target_identity(t)
        drain = last(t.control("quiesce", self.id))
        if not drain.isdigit():
            raise RestoreHostError("The presigned upload drain window is invalid.")
        t.compose("stop", "worker", "beat")
        inventory(t, stopped=True, allow_backend=True)
        # No controller child holds the lock; this process remains its sole owner.
        time.sleep(int(drain))
        with (i.private / "pre-restore.dump").open("xb") as output:
            os.chmod(output.name, 0o600)
            t.sql(DUMP, output=output)
        if (i.private / "pre-restore.dump").stat().st_size <= 0:
            raise RestoreHostError("The mandatory pre-restore dump is empty.")
        name = "spaceworks_restore_" + self.id.replace("-", "")
        t.sql('createdb -U "$POSTGRES_USER" ' + name)
        with (i.private / "bundle/database.dump").open("rb") as source:
            t.sql('pg_restore --exit-on-error --single-transaction --no-owner --no-acl -U "$POSTGRES_USER" -d ' + name,
                  input_file=source)
        t.grants(temporary_database=name)
        if i.kind != FULL_FORMAT:
            result = t.compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
                "orchestration-ready", "/app/scripts/restore_legacy_preview.py", name,
                input_bytes=json.dumps({"full_target_identity": self.old_probe["target_record"]}).encode())
            if last(result) != "legacy-preview-identity-ok":
                raise RestoreHostError("Historical same-host preview identity is unavailable.")
        print("The target is quiesced. Review the real database diff in the console and choose proceed, reset or abort.", flush=True)
        decision = last(t.control("diff-wait", self.id, "--archive-database-name", name))
        t.sql('dropdb -U "$POSTGRES_USER" ' + name)
        if decision not in {"proceed", "reset", "abort"}:
            raise RestoreHostError("The durable restore decision is invalid.")
        private_json(i.private / "decision.json", {"restore_id": self.id, "decision": decision})
        if decision == "abort":
            self.finish_abort()
            return None
        i.export_control(decision)
        return decision

    def finish_abort(self):
        proof = fixed_probe(self.t, self.id)["recovery_proof"]
        if (proof["mode"], proof["active_restore"], proof["stage"], proof["decision"]) != ("normal", None, "aborted", "abort"):
            raise RestoreHostError("The explicit harmless abort has not durably returned the database to normal.")
        if (self.t.validate() != self.old_facts or self.t.static_env.read_bytes() != self.old_environment
                or self.t.compose("config", "--format", "json", json_result=True) != self.t.config):
            raise RestoreHostError("The explicit abort no longer has the exact original environment/topology.")
        if read_marker(self.t.host / "public/restore-marker.json") != self.old_marker or target_identity(self.t) != self.identity:
            raise RestoreHostError("The abort target or original marker changed.")
        inventory(self.t, stopped=True, allow_backend=True)
        private_json(self.i.private / "abort-verified.json", proof)
        self.t.compose("up", "-d", "--no-deps", "worker", "beat")
        inventory(self.t)
        print("Explicit abort verified; original environment, queue and runtime retained.", flush=True)

    def phase(self, name, evidence):
        detail = {"binding": self.binding, "evidence_sha256": json_digest(evidence)}
        return self.ledger.begin(name, detail)

    def done(self, begun, evidence):
        self.ledger.finish(begun, {"binding": self.binding, "evidence_sha256": json_digest(evidence)})

    def restore(self, decision):
        t, i = self.t, self.i
        config = ConfigurationTransition(t, i.private, continuity=i.continuity if i.prospective else None)
        operation = OperationIdentity(self.id, i.outer_sha256,
            i.manifest["capture_id"] if i.kind == FULL_FORMAT else str(uuid.uuid4()), t.pointer.generation)
        self.operation = operation
        self.binding = phase_binding(operation, config.configuration_sha256, config.topology_sha256)
        private_json(i.private / "operation.json", {"operation": asdict(operation), "binding": self.binding,
            "capture_provenance": "signed-full" if i.kind == FULL_FORMAT else "local-legacy-operation",
            "decision": decision})
        index = {"private": str(i.private), "public": str(i.public), "work": str(i.work)}
        private_json(t.ops / "private" / f"inplace-index-{self.id}.json", index)
        actual = inventory(t, stopped=True, allow_backend=True)
        self.writer_ids = [c["Id"] for c in actual if c["Config"]["Labels"].get("com.docker.compose.service") == "backend"]
        self.marker.begin(operation, target_identity(t), config.configuration_sha256, config.topology_sha256,
                          "signed-full" if i.kind == FULL_FORMAT else "local-legacy-operation")
        self.blocked = True
        t.compose("stop", "backend", "worker", "beat")
        inventory(t, stopped=True)
        no_database_sessions(t)
        begun = self.phase("inplace-configuration-verified", config.facts)
        config.install()
        digest_value = admit_configuration(t)
        inventory(t, stopped=True)
        i.preflight(digest_value)  # Installed NEW environment must pass before SQL.
        verify_installed_configuration(t, i.private)
        self.done(begun, config.facts)
        begun = self.phase("inplace-sql-restored", {"artifact": i.outer_sha256})
        t.control("stage", self.id, "db_restoring")
        inventory(t, stopped=True)
        no_database_sessions(t)
        with (i.private / "bundle/database.dump").open("rb") as source:
            t.sql(RESTORE, input_file=source)
        identity = {"full_target_identity": self.old_probe["target_record"], "restore_operation": asdict(operation)}
        t.grants(identity=json.dumps(identity).encode(), legacy=i.kind != FULL_FORMAT)
        if target_identity(t) != self.identity:
            raise RestoreHostError("Restored target identity verification failed.")
        t.control("rehydrate", self.id, "--archive-id", i.metadata["archive_id"], "--kind", i.metadata["kind"],
            "--requested-by", str(i.metadata["requested_by"]), "--control-record", i.public_app + "/restore-control.json",
            "--manifest", i.public_app + "/bundle/manifest.json")
        t.control("verify-source-objects", self.id, "--manifest", i.public_app + "/bundle/manifest.json")
        self.done(begun, fixed_probe(t, self.id))
        begun = self.phase("inplace-objects-verified", {"manifest": json_digest(i.manifest)})
        t.control("restore-objects", self.id, "--bundle-root", i.public_app + "/bundle", "--manifest",
            i.public_app + "/bundle/manifest.json", "--journal", t.app_path(i.work / "swap-journal.jsonl"))
        journal_hash = seal_file(i.work / "swap-journal.jsonl", i.private / "swap-journal.jsonl")
        delegate_file(i.private / "swap-journal.jsonl", i.public / "swap-journal.jsonl", public=True)
        t.control("verify-restored-objects", self.id, "--manifest", i.public_app + "/bundle/manifest.json",
                  "--journal", i.public_app + "/swap-journal.jsonl")
        self.done(begun, {"journal_sha256": journal_hash, "manifest_sha256": json_digest(i.manifest)})
        begun = self.phase("inplace-readiness-verified", {"restore_id": self.id})
        t.control("stage", self.id, "validating")
        t.control("validate", self.id)
        i.preflight(digest_value)
        hashes = verify_installed_configuration(t, i.private)
        if target_identity(t) != self.identity:
            raise RestoreHostError("Successful restore target identity changed.")
        inventory(t, stopped=True)
        no_database_sessions(t)
        self.done(begun, fixed_probe(t, self.id))
        if i.metadata["kind"] == "disaster" or decision == "reset":
            t.control("quarantine", self.id, "--reason", "Verified in-place restore requires recovered-principal acknowledgement.")
        else:
            t.control("complete", self.id)
        self.marker.complete(operation, target_identity(t), fixed_probe(t, self.id)["recovery_proof"],
                             configuration_sha256=hashes[0], topology_sha256=hashes[1])
        t.compose("up", "-d", "--no-deps", "backend")
        if i.metadata["kind"] != "disaster" and decision != "reset":
            t.compose("up", "-d", "--no-deps", "worker", "beat")
            inventory(t)
        else:
            inventory(t, stopped=True, allow_backend=True)
        print("Restore verified. Recovery copies retained. Quarantine requires recovered-principal acknowledgement and explicit host resume.", flush=True)

    def retain_failure(self):
        marker = read_marker(self.t.host / "public/restore-marker.json")
        if hasattr(self, "operation"):
            if marker.state != MarkerState.RESTORE_BLOCKED and self.blocked:
                hashes = verify_installed_configuration(self.t, self.i.private)
                self.marker.block_failed_start(self.operation, self.identity,
                    configuration_sha256=hashes[0], topology_sha256=hashes[1])
                marker = read_marker(self.t.host / "public/restore-marker.json")
            if marker.state == MarkerState.RESTORE_BLOCKED and marker.operation == self.operation:
                stop_current_writers(self.t)
                private_json(self.i.private / "failure.json", {"restore_id": self.id, "state": "blocked-manual-recovery"})
        print(f"Restore did not release writers. Retain private recovery evidence at {self.i.private}.", flush=True)


def stop_current_writers(transport):
    """Narrow shutdown uses known project/image identities even if wrapper config is torn."""
    project = transport.config["name"]
    ids = transport.docker("ps", "-q", "--filter", f"label=com.docker.compose.project={project}").splitlines()
    containers = transport.docker("inspect", *ids, json_result=True) if ids else []
    writers = [item["Id"] for item in containers if item["Image"] == transport.admitted_image_id or
        item["Config"].get("Labels", {}).get("com.docker.compose.service") in {
            "backend", "worker", "beat", "cron", "candidate-backend", "migrate"}]
    if writers:
        transport.docker("stop", *writers)
    remaining = transport.docker("ps", "-q", "--filter", f"label=com.docker.compose.project={project}").splitlines()
    if set(writers) & set(remaining):
        raise RestoreHostError("The host marker is blocked, but writer shutdown could not be proved.")
