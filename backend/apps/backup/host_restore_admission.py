"""Resolved configuration and actual writer inventory for one bundled topology."""

from dataclasses import asdict
import json
import re
from urllib.parse import urlsplit, unquote

from .host_marker import DatabaseIdentity, read_marker
from .host_restore_transport import RestoreHostError, trusted
from .topology import validate_host_orchestration_contract


APP_ROLES = ("backend", "worker", "beat")
ENTRYPOINT = ["python", "/app/scripts/spaceworks_entrypoint.py"]


def _remember_redis_volume(transport, name):
    if (not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{64}", name)
            or getattr(transport, "redis_volume_identity", name) != name):
        raise RestoreHostError("The admitted anonymous Redis volume identity changed or is malformed.")
    transport.redis_volume_identity = name


def reuse_redis_admission(transport, private):
    """Recover only the observed identity from the existing root-private receipt."""
    record = json.loads(trusted(private / "admission-old.json", private=True).read_bytes())
    redis = [item for item in record["actual"] if
        item["Config"].get("Labels", {}).get("com.docker.compose.service") == "redis"]
    if len(redis) != 1:
        raise RestoreHostError("The original actual Redis admission inventory is unavailable.")
    declared = record["resolved"]["services"]["redis"].get("volumes", [])
    if not any(item["target"] == "/data" for item in declared):
        mounts = [item for item in redis[0].get("Mounts", []) if item.get("Destination") == "/data"]
        if len(mounts) != 1:
            raise RestoreHostError("The original anonymous Redis volume identity is unavailable.")
        _remember_redis_volume(transport, mounts[0].get("Name"))


def _admit_implicit_redis(transport, service, image, mounts):
    if (service.get("image") != "redis:7-alpine" or service.get("volumes")
            or image["Config"].get("Volumes") != {"/data": {}}
            or set(mounts) != {"/data"}):
        raise RestoreHostError("Only the bundled image-declared anonymous Redis data volume is supported.")
    mount = mounts["/data"]
    name = mount.get("Name")
    if (mount.get("Type") != "volume" or mount.get("Driver") != "local" or mount.get("RW") is not True
            or not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{64}", name)):
        raise RestoreHostError("The implicit Redis mount is not the supported anonymous local RW volume.")
    volumes = transport.docker("volume", "inspect", name, json_result=True)
    if len(volumes) != 1:
        raise RestoreHostError("The actual anonymous Redis volume facts are unavailable.")
    volume = volumes[0]
    if (volume.get("Name") != name or volume.get("Driver") != "local" or volume.get("Scope") != "local"
            or volume.get("Options") not in (None, {}) or not volume.get("Mountpoint")
            or volume["Mountpoint"] != mount.get("Source")):
        raise RestoreHostError("Anonymous Redis volume driver options or backing storage are unsupported.")
    # This binds an observed daemon volume, never asserts project ownership of it.
    _remember_redis_volume(transport, name)
    mounts.pop("/data")


def admit_configuration(transport):
    config = transport.config
    contract = validate_host_orchestration_contract(config)
    scheduler = contract.get("scheduler", {})
    if scheduler.get("mode") != "image" or scheduler.get("services") != ["beat"]:
        raise RestoreHostError("Only the bundled image scheduler is admitted for in-place restore.")
    services = config["services"]
    database = services["db"]
    if (database.get("image") != "postgres:16" or database.get("command") is not None
            or database.get("entrypoint") is not None):
        raise RestoreHostError("Only the unchanged bundled PostgreSQL 16 service is supported.")
    db_env = database["environment"]
    baseline = services["backend"]["environment"]
    pointer = urlsplit(transport.pointer.database_url)
    if (pointer.hostname, pointer.port or 5432, unquote(pointer.path.lstrip("/"))) != (
        "db", 5432, db_env["POSTGRES_DB"]
    ) or pointer.scheme not in {"postgres", "postgresql"}:
        raise RestoreHostError("Application pointer and bundled SQL service select different databases.")
    bootstrap = services.get("orchestration-ready", {})
    bootstrap_env = bootstrap.get("environment", {})
    expected_bootstrap = {
        "DATABASE_URL": "postgres://" + db_env["POSTGRES_USER"] + ":" + db_env["POSTGRES_PASSWORD"] + "@db:5432/" + db_env["POSTGRES_DB"],
        "SPACEWORKS_RUNTIME_DATABASE_URL": transport.pointer.database_url,
        "SPACEWORKS_HOST_MARKER_WRITE_PATH": "/host-state/restore-marker.json",
        "SPACEWORKS_SCHEDULER_MODE": "image", "SPACEWORKS_SCHEDULER_SERVICES": "beat",
    }
    if (bootstrap.get("image") != services["backend"]["image"] or bootstrap.get("user") != "0:0"
            or bootstrap.get("entrypoint") != ["python", "/app/scripts/bootstrap_host_orchestration.py"]
            or bootstrap.get("command") is not None or bootstrap_env != expected_bootstrap):
        raise RestoreHostError("The fixed maintenance service differs from the admitted application transport.")
    mounts = bootstrap.get("volumes", [])
    if (len(mounts) != 1 or mounts[0].get("type") != "bind" or mounts[0].get("target") != "/host-state"
            or mounts[0].get("source") != str(transport.host / "public") or mounts[0].get("read_only")):
        raise RestoreHostError("The fixed maintenance marker mount is unsupported.")
    digest = baseline.get("SPACEWORKS_OCI_DIGEST", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RestoreHostError("An actual immutable OCI repository digest is required.")
    image = transport.docker("image", "inspect", services["backend"]["image"], json_result=True)[0]
    if (image["Config"].get("Entrypoint") != ENTRYPOINT or not any(
            item.endswith("@" + digest) for item in image.get("RepoDigests", []))):
        raise RestoreHostError("The fixed image lacks the exact admitted repository digest and entrypoint.")
    if getattr(transport, "admitted_image_id", image["Id"]) != image["Id"]:
        raise RestoreHostError("The previously admitted immutable image changed.")
    transport.admitted_image_id, transport.admitted_digest = image["Id"], digest
    for role in APP_ROLES:
        service = services[role]
        if service["image"] != services["backend"]["image"]:
            raise RestoreHostError("Application roles do not share the exact admitted image.")
        env = service["environment"]
        command = service.get("command", [])
        entrypoint = service.get("entrypoint")
        if entrypoint is None:
            entrypoint = image["Config"].get("Entrypoint")
        if (not isinstance(command, list) or command[:2] != ["--role", role]
                or entrypoint != ENTRYPOINT):
            raise RestoreHostError("An application role command is unsupported.")
        if role == "backend":
            prefix = "python manage.py collectstatic --noinput && "
            gunicorn = "gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers "
            suffix = " --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile -"
            if (len(command) != 5 or command[:4] != ["--role", "backend", "sh", "-c"]
                    or not re.fullmatch(re.escape(prefix) + r"(?:exec )?" + re.escape(gunicorn)
                        + r"[1-9][0-9]* --timeout [1-9][0-9]*" + re.escape(suffix), command[4])):
                raise RestoreHostError("Custom backend commands are unsupported.")
        if role == "worker" and command != ["--role", "worker", "celery", "-A", "config", "worker",
                                             "-l", "info", "--concurrency", env.get("CELERY_CONCURRENCY", "4")]:
            # Concurrency is interpolation-only; accept only its numeric resolved value.
            if (len(command) != 10 or command[:9] != ["--role", "worker", "celery", "-A", "config",
                    "worker", "-l", "info", "--concurrency"] or not str(command[9]).isdigit()):
                raise RestoreHostError("Custom worker queues or commands are unsupported.")
        if role == "beat" and command != ["--role", "beat", "celery", "-A", "config", "beat", "-l", "info",
                                           "--schedule", "/var/lib/celery/celerybeat-schedule"]:
            raise RestoreHostError("Custom scheduler commands are unsupported.")
        for name in ("DATABASE_URL", "SPACEWORKS_DB_POINTER_GENERATION", "SPACEWORKS_TASK_GENERATION",
                     "SPACEWORKS_OCI_DIGEST", "CELERY_BROKER_URL"):
            if env.get(name, "") != baseline.get(name, ""):
                raise RestoreHostError("Application producers disagree on target configuration.")
        if env.get("DATABASE_URL") != transport.pointer.database_url:
            raise RestoreHostError("Resolved application database pointer drifted.")
        if any(name.startswith("CELERY_") and any(word in name for word in ("QUEUE", "ROUT", "EXCHANGE"))
               for name in env):
            raise RestoreHostError("Competing task routing configuration is unsupported.")
        expected = {"/run/spaceworks-host": (str(transport.host / "public"), True),
                    "/var/lib/spaceworks/ops/work": (str(transport.ops / "work"), False),
                    "/var/lib/spaceworks/ops/operation.lock": (str(transport.ops / "operation.lock"), False)}
        mounts = {m["target"]: m for m in service.get("volumes", [])}
        for target, (source, readonly) in expected.items():
            mount = mounts.get(target, {})
            if mount.get("type") != "bind" or mount.get("source") != source or bool(mount.get("read_only")) != readonly:
                raise RestoreHostError("A required host authority mount is unsupported.")
    if baseline.get("CELERY_BROKER_URL") != "redis://redis:6379/0":
        raise RestoreHostError("Only the bundled single-default-queue Redis transport is supported.")
    return digest


def inventory(transport, *, stopped=False, allow_backend=False):
    config = transport.config
    project = config.get("name")
    if not project:
        raise RestoreHostError("Resolved Compose project identity is unavailable.")
    ids = transport.docker("ps", "-q", "--filter", f"label=com.docker.compose.project={project}").splitlines()
    containers = transport.docker("inspect", *ids, json_result=True) if ids else []
    seen = set()
    for container in containers:
        labels = container["Config"].get("Labels") or {}
        role = labels.get("com.docker.compose.service")
        if role in seen or labels.get("com.docker.compose.oneoff", "False").lower() != "false":
            raise RestoreHostError("Duplicate or one-off project processes prevent restore admission.")
        seen.add(role)
        if role not in {"backend", "worker", "beat", "db", "redis", "minio", "frontend", "caddy"}:
            raise RestoreHostError("An unknown or candidate project process prevents restore admission.")
        service = config["services"].get(role)
        if service is None:
            raise RestoreHostError("Actual project process lacks a trusted service declaration.")
        image = transport.docker("image", "inspect", service["image"], json_result=True)[0]
        if role in APP_ROLES and image["Config"].get("Entrypoint") != ENTRYPOINT:
            raise RestoreHostError("Application image does not use the admitted marker entrypoint.")
        if container["Image"] != image["Id"]:
            raise RestoreHostError("Actual project image differs from the resolved installed image.")
        actual = container["Config"]
        command = service.get("command")
        if command is None:
            command = image["Config"].get("Cmd")
        entrypoint = service.get("entrypoint")
        if entrypoint is None:
            entrypoint = image["Config"].get("Entrypoint")
        if actual.get("Cmd") != command or actual.get("Entrypoint") != entrypoint:
            raise RestoreHostError("Actual project process command differs from trusted configuration.")
        expected_env = dict(pair.split("=", 1) for pair in image["Config"].get("Env", []))
        expected_env.update(service.get("environment", {}))
        actual_env = dict(pair.split("=", 1) for pair in actual.get("Env", []))
        if expected_env != actual_env:
            raise RestoreHostError("Actual project process environment differs from trusted configuration.")
        actual_mounts = container.get("Mounts", [])
        mounts = {m["Destination"]: m for m in actual_mounts}
        if len(mounts) != len(actual_mounts):
            raise RestoreHostError("Actual project process has repeated mount destinations.")
        for declared in service.get("volumes", []):
            mount = mounts.pop(declared["target"], {})
            if mount.get("Type") != declared["type"] or mount.get("RW") != (not bool(declared.get("read_only"))):
                raise RestoreHostError("Actual project mount permissions differ from trusted configuration.")
            if declared["type"] == "bind" and mount.get("Source") != declared["source"]:
                raise RestoreHostError("Actual project bind mount differs from trusted configuration.")
            if declared["type"] == "volume":
                expected_name = config["volumes"][declared["source"]]["name"]
                if mount.get("Name") != expected_name:
                    raise RestoreHostError("Actual project volume differs from trusted configuration.")
        if role == "redis" and not any(m["target"] == "/data" for m in service.get("volumes", [])):
            _admit_implicit_redis(transport, service, image, mounts)
        elif role == "redis" and getattr(transport, "redis_volume_identity", None):
            raise RestoreHostError("The admitted anonymous Redis volume became an explicit mount.")
        if mounts:
            raise RestoreHostError("Actual project process has unexplained mounts.")
        if role in APP_ROLES:
            digest = service["environment"]["SPACEWORKS_OCI_DIGEST"]
            if not any(value.endswith("@" + digest) for value in image.get("RepoDigests", [])):
                raise RestoreHostError("Declared OCI digest does not match actual image repository facts.")
            if stopped and not (allow_backend and role == "backend"):
                raise RestoreHostError("An actual application writer is still running.")
    if not stopped and not set(APP_ROLES) <= seen:
        raise RestoreHostError("The original application writer inventory is incomplete.")
    if (not stopped or getattr(transport, "redis_volume_identity", None)) and "redis" not in seen:
        raise RestoreHostError("The actual Redis inventory is incomplete.")
    return containers


def target_identity(transport):
    probe = transport.compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
        "orchestration-ready", "/app/scripts/restore_database_probe.py", json_result=True)
    live = probe["identity"]
    db_ids = transport.compose("ps", "-q", "db").splitlines()
    if len(db_ids) != 1:
        raise RestoreHostError("Exactly one bundled SQL service must be running.")
    actual_db = transport.docker("inspect", db_ids[0], json_result=True)[0]
    addresses = {net.get("IPAddress") for net in actual_db["NetworkSettings"]["Networks"].values()}
    if probe["physical"]["address"] not in addresses or probe["physical"]["port"] != 5432:
        raise RestoreHostError("Queried application endpoint is not the admitted bundled SQL container.")
    # Independently use db service POSTGRES_DB transport, not the app URL.
    sql = '''psql -X -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT json_build_object('name',current_database(),'oid',(SELECT oid::bigint FROM pg_database WHERE datname=current_database()),'uuid',(SELECT database_uuid::text FROM backup_deploymentdatabaseidentity WHERE id=1),'system',(SELECT system_identifier::text FROM pg_control_system()))"'''
    db = json.loads(transport.sql(sql))
    identity = DatabaseIdentity(live["endpoint"]["database"], live["oid"], {
        "endpoint": live["endpoint"], "database_uuid": live["database_uuid"],
        "system_identifier": live["system_identifier"],
    })
    if db != {"name": identity.name, "oid": identity.oid,
              "uuid": live["database_uuid"], "system": live["system_identifier"]}:
        raise RestoreHostError("Bundled SQL transport and application identity disagree.")
    if read_marker(transport.host / "public/restore-marker.json").require_bound_database() != identity:
        raise RestoreHostError("Queried immutable target identity disagrees with the bound host marker.")
    return identity


def no_database_sessions(transport):
    value = transport.sql('''psql -X -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'"''')
    if value != "0":
        raise RestoreHostError("Unexplained database sessions remain; no session was terminated.")
