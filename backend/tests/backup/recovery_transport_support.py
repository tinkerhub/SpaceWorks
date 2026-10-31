"""Deterministic Docker/SQL wire responses, not an attested or restored host."""

from copy import deepcopy
import json
import shlex
from types import SimpleNamespace

from apps.backup.host_pointer import read_pointer
from apps.backup.host_restore_admission import ENTRYPOINT
from apps.backup.host_restore_configuration import CONTINUITY
from apps.backup.host_restore_transport import RestoreHostError
from apps.backup.host_topology_record import configuration_facts, validate_compose_wrapper, write_topology_record
from tests.backup.recovery_test_support import RESTORE_ID, private, recovery_proof


VOLUME = "d" * 64
DIGEST = "sha256:" + "e" * 64


class SyntheticTransport:
    def __init__(self, rig, root):
        self.rig, self.root = rig, root
        self.ops, self.host = rig.ops, rig.marker.parents[1]
        self.ops.joinpath("work").mkdir(mode=0o700, exist_ok=True)
        self.static_env = private(root / ".env", b"SPACEWORKS_SCHEDULER_MODE=image\nTARGET_ONLY=keep\n")
        self.files = [private(root / "docker-compose.prod.yml", b"synthetic committed family\n")]
        self.record = self.ops / "compose-topology.json"
        write_topology_record(self.record, configuration_facts(topology="bundled", static_env=self.static_env, compose_files=self.files))
        self.pointer = read_pointer(rig.pointer)
        self.events, self.failure = [], None
        self.mode = "normal"
        self.config = self.resolved(self.static_env)
        self.facts = self.validate()
        self.running = {role for role in ("backend", "worker", "beat", "db", "redis")}
        self.admitted_image_id, self.admitted_digest = "app-image", DIGEST
        self.redis_name = VOLUME
        self.volume_facts = {"Name": VOLUME, "Driver": "local", "Scope": "local", "Options": None,
            "Mountpoint": "/var/lib/docker/volumes/" + VOLUME + "/_data"}

    def hit(self, event):
        self.events.append(event)
        if event == self.failure:
            raise RestoreHostError("synthetic transport failure: " + event)

    def resolved(self, path):
        env = {name: "old-" + name for name in CONTINUITY}
        env.update(DATABASE_URL=self.pointer.database_url, SPACEWORKS_DB_POINTER_GENERATION="7",
            SPACEWORKS_TASK_GENERATION="", SPACEWORKS_OCI_DIGEST=DIGEST, CELERY_BROKER_URL="redis://redis:6379/0")
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key in env:
                env[key] = shlex.split(value)[0] if value else ""
        mounts = [{"type": "bind", "source": str(source), "target": target, "read_only": ro}
            for target, source, ro in [("/run/spaceworks-host", self.host / "public", True),
                ("/var/lib/spaceworks/ops/work", self.ops / "work", False),
                ("/var/lib/spaceworks/ops/operation.lock", self.ops / "operation.lock", False)]]
        # Explicit legacy control: historical && gunicorn remains admissible.
        backend = "python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile -"
        commands = {"backend": ["--role", "backend", "sh", "-c", backend],
            "worker": ["--role", "worker", "celery", "-A", "config", "worker", "-l", "info", "--concurrency", "4"],
            "beat": ["--role", "beat", "celery", "-A", "config", "beat", "-l", "info", "--schedule", "/var/lib/celery/celerybeat-schedule"]}
        services = {role: {"image": "app:fixed", "environment": dict(env), "command": cmd, "volumes": deepcopy(mounts)}
            for role, cmd in commands.items()}
        services["db"] = {"image": "postgres:16", "environment": {"POSTGRES_USER": "owner", "POSTGRES_PASSWORD": "test", "POSTGRES_DB": "recovery_target"}}
        services["redis"] = {"image": "redis:7-alpine"}
        services["orchestration-ready"] = {"image": "app:fixed", "user": "0:0",
            "entrypoint": ["python", "/app/scripts/bootstrap_host_orchestration.py"],
            "environment": {"DATABASE_URL": "postgres://owner:test@db:5432/recovery_target",
                "SPACEWORKS_RUNTIME_DATABASE_URL": self.pointer.database_url,
                "SPACEWORKS_HOST_MARKER_WRITE_PATH": "/host-state/restore-marker.json",
                "SPACEWORKS_SCHEDULER_MODE": "image", "SPACEWORKS_SCHEDULER_SERVICES": "beat"},
            "volumes": [{"type": "bind", "target": "/host-state", "source": str(self.host / "public")}]}
        return {"name": "private-stage3", "services": services, "x-spaceworks-host-orchestration": {
            "scheduler": {"mode": "image", "services": ["beat"]},
            "pointer": {"mode": "atomic-file", "path": "/var/lib/spaceworks/ops/database-pointer.env", "static_environment": ".env"},
            "database_identity": "endpoint-plus-queried-uuid", "sibling_lifecycle": "bundled-owned-database",
            "writer_services": ["backend", "worker", "beat"]}}

    def validate(self):
        return validate_compose_wrapper(topology="bundled", static_env=self.static_env,
            pointer_file=self.rig.pointer, topology_record=self.record, compose_files=self.files)

    def image(self, reference):
        role = {"app:fixed": "app", "postgres:16": "db", "redis:7-alpine": "redis"}[reference]
        return {"Id": role + "-image", "RepoDigests": ["fixture@" + DIGEST] if role == "app" else [],
            "Config": {"Entrypoint": ENTRYPOINT if role == "app" else None,
                "Volumes": {"/data": {}} if role == "redis" else {}, "Env": []}}

    def container(self, role):
        service = self.config["services"][role]
        image = self.image(service["image"])
        mounts = [{"Type": m["type"], "Destination": m["target"], "Source": m["source"],
            "RW": not m.get("read_only", False)} for m in service.get("volumes", [])]
        if role == "redis":
            mounts += [{"Type": "volume", "Name": self.redis_name, "Driver": "local", "Destination": "/data", "RW": True,
                "Source": self.volume_facts["Mountpoint"]}]
        return {"Id": role, "Image": image["Id"], "State": {"Running": True},
            "Config": {"Labels": {"com.docker.compose.service": role, "com.docker.compose.project": "private-stage3"},
                "Cmd": service.get("command"), "Entrypoint": service.get("entrypoint", image["Config"]["Entrypoint"]),
                "Env": [k + "=" + v for k, v in service.get("environment", {}).items()]}, "Mounts": mounts,
            "NetworkSettings": {"Networks": {"private": {"IPAddress": "172.19.0.2"}}}}

    def docker(self, *args, json_result=False):
        self.events.append(("docker", args))
        if args[:2] == ("image", "inspect"):
            return [self.image(args[2])]
        if args[:2] == ("volume", "inspect"):
            return [deepcopy(self.volume_facts)]
        if args[:1] == ("ps",):
            return "\n".join(sorted(self.running))
        if args[:1] == ("inspect",):
            return [self.container(role) for role in args[1:]]
        if args[:1] == ("stop",):
            self.running -= set(args[1:])
            return ""
        if args[:1] == ("compose",):
            return self.resolved(__import__("pathlib").Path(args[args.index("--env-file") + 1]))
        raise AssertionError(args)

    def probe(self):
        server = self.rig.identity.server_identity
        identity = {**server, "oid": self.rig.identity.oid}
        return {"identity": identity, "physical": {"address": "172.19.0.2", "port": 5432},
            "target_record": {"fixture": "synthetic SQL wire response"},
            "recovery_state": {"mode": self.mode, "active_restore": None if self.mode == "normal" else RESTORE_ID},
            "recovery_proof": recovery_proof()}

    def compose(self, *args, json_result=False, **kwargs):
        if args[0] == "config":
            return self.resolved(self.static_env)
        if args[0] == "stop":
            self.hit("stop:" + ",".join(args[1:]))
            self.running -= set(args[1:])
            return ""
        if args[0] == "up":
            self.hit("start:" + ",".join(args[3:]))
            self.running |= set(args[3:])
            return ""
        if args[:3] == ("ps", "-q", "db"):
            return "db"
        if "restore_database_probe.py" in " ".join(args):
            return self.probe()
        raise AssertionError(args)

    def app_path(self, path):
        return str(path)

    def sql(self, command, *, input_file=None, output=None):
        if command.startswith("pg_dump"):
            self.hit("dump")
            output.write(b"synthetic SQL rollback copy")
            return
        if command.startswith("pg_restore"):
            self.hit("preview-sql" if "-d spaceworks_restore_" in command else "sql-restore")
            return
        if "pg_stat_activity" in command:
            self.hit("sessions")
            return "0"
        if "json_build_object" in command:
            server = self.rig.identity.server_identity
            return json.dumps({"name": self.rig.identity.name, "oid": self.rig.identity.oid,
                "uuid": server["database_uuid"], "system": server["system_identifier"]})
        if command.startswith(("createdb", "dropdb")):
            self.hit(command.split()[0])
            return
        raise AssertionError(command)

    def grants(self, **kwargs):
        self.hit("grants")

    def control(self, action, *args):
        self.hit("control:" + action)
        if action == "claim":
            return "claimed"
        if action == "quiesce":
            self.mode = "quiesced"
            return "0"
        if action == "diff-wait":
            return "proceed"
        if action == "restore-objects":
            __import__("pathlib").Path(args[args.index("--journal") + 1]).write_bytes(b"")
        if action == "quarantine":
            self.mode = "quarantined"
        return ""


def lifecycle_inputs(root):
    private_dir = root / "ops/private/inplace-synthetic"
    # mkdir(parents=True) does not apply the leaf mode to intermediate parents.
    private_dir.parent.mkdir(mode=0o700)
    private_dir.mkdir(mode=0o700)
    private(private_dir / "bundle/database.dump", b"synthetic source dump")
    public = root / "public-input"
    public.mkdir(mode=0o755)
    work = root / "work-input"
    work.mkdir(mode=0o700)
    return SimpleNamespace(restore_id=RESTORE_ID, outer_sha256="a" * 64,
        private=private_dir, public=public, work=work, public_app="/public-input",
        manifest={"capture_id": "670a9c81-1234-4aaa-8c81-0123456789ab"}, kind="spaceworks-deployment-full-v1",
        metadata={"archive_id": "670a9c81-1234-4aaa-8c81-0123456789ab", "kind": "disaster", "requested_by": 1},
        continuity=None, prospective=None)
