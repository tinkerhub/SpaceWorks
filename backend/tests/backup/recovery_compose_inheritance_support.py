"""Real Compose JSON producer; independently scripted, synthetic inspect wire facts.

No daemon, image inspection, root attestation, database or restore is performed.
Container argv and mounts are fixed expectations, never echoed from service argv.
Only baseline service environments are projected into the synthetic wire snapshot.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from apps.backup.host_pointer import parse_pointer_text


ROOT = Path(__file__).resolve().parents[3]
APP_ROLES = ("backend", "worker", "beat")
RUNNING = (*APP_ROLES, "db", "redis", "minio", "frontend")
PROJECT = "compose-inheritance"
DIGEST = "sha256:" + "e" * 64
# Independent Dockerfile expectations, deliberately not imported from admission.
APP_ENTRYPOINT = ["python", "/app/scripts/spaceworks_entrypoint.py"]
APP_DEFAULT_CMD = ["--role", "backend", "gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
COMMANDS = {
    "backend": ["--role", "backend", "sh", "-c",
        "python manage.py collectstatic --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 "
        "--workers 3 --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 "
        "--access-logfile - --error-logfile -"],
    "worker": ["--role", "worker", "celery", "-A", "config", "worker", "-l", "info", "--concurrency", "4"],
    "beat": ["--role", "beat", "celery", "-A", "config", "beat", "-l", "info", "--schedule", "/var/lib/celery/celerybeat-schedule"],
    "db": ["postgres"], "redis": ["redis-server"],
    "minio": ["server", "/data", "--console-address", ":9001"],
    "frontend": ["nginx", "-g", "daemon off;"],
}


def render_committed_compose(root):
    """Invoke the installed Linux CLI once, using only dedicated interpolation.

    The committed build overlay is rendered, never built. HOME/config are isolated;
    even an unexpected daemon request would hit a nonexistent socket, not the host.
    Missing Linux/docker/Compose or invalid producer output is a failure, not a skip.
    """
    if sys.platform != "linux":
        pytest.fail("Compose inheritance requires Linux and an installed Docker Compose CLI.", pytrace=False)
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("Installed docker CLI with the Compose plugin is required.", pytrace=False)
    host, ops = root / "host", root / "ops"
    (host / "public").mkdir(parents=True)
    (ops / "work").mkdir(parents=True)
    (ops / "operation.lock").touch(mode=0o600)
    home = root / "cli-home"
    (home / ".docker").mkdir(parents=True)
    static = root / ".env"
    static.write_text("\n".join([
        "POSTGRES_USER=synthetic_owner", "POSTGRES_PASSWORD=synthetic_password",
        "POSTGRES_DB=synthetic_target", "SECRET_KEY=synthetic-compose-only-secret-key",
        "ALLOWED_HOSTS=synthetic.invalid", "MINIO_ROOT_USER=synthetic_storage",
        "MINIO_ROOT_PASSWORD=synthetic_storage_password", "SPACEWORKS_SCHEDULER_MODE=image",
        f"SPACEWORKS_OCI_DIGEST={DIGEST}", f"SPACEWORKS_HOST_STATE_DIR={host}",
        f"SPACEWORKS_OPS_HOST_DIR={ops}", "MAKERSPACE_IMAGE_TAG=synthetic",
        "MAKERSPACE_BACKEND_IMAGE=example.invalid/spaceworks/backend",
        "MAKERSPACE_FRONTEND_IMAGE=example.invalid/spaceworks/frontend",
    ]) + "\n", encoding="utf-8")
    static.chmod(0o600)
    pointer = ops / "database-pointer.env"
    pointer.write_text("DATABASE_URL='postgres://synthetic_app:synthetic_runtime@db:5432/synthetic_target'\n"
        "SPACEWORKS_DB_POINTER_GENERATION=7\n", encoding="utf-8")
    pointer.chmod(0o600)
    argv = [docker, "compose", "--project-name", PROJECT,
        "--env-file", str(static), "--env-file", str(pointer),
        "-f", str(ROOT / "docker-compose.prod.yml"),
        "-f", str(ROOT / "docker/compose.build.yml"), "config", "--format", "json"]
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home), "DOCKER_CONFIG": str(home / ".docker"), "LANG": "C.UTF-8",
        "DOCKER_HOST": "unix://" + str(root / "no-daemon.sock"),
    }
    try:
        result = subprocess.run(argv, cwd=ROOT, env=environment, capture_output=True,
            timeout=30, check=False, close_fds=True)
    except (OSError, subprocess.TimeoutExpired):
        pytest.fail("Installed Docker Compose config invocation failed (output withheld).", pytrace=False)
    if result.returncode:
        pytest.fail("Installed Docker Compose config failed; CLI/plugin required (output withheld).", pytrace=False)
    try:
        config = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        pytest.fail("Installed Docker Compose returned invalid JSON (output withheld).", pytrace=False)
    if not isinstance(config, dict) or config.get("name") != PROJECT:
        pytest.fail("Installed Docker Compose returned an unexpected document (output withheld).", pytrace=False)
    return config, host, ops, parse_pointer_text(pointer.read_text(encoding="utf-8"))


class SyntheticInspectTransport:
    """Seven synthetic running containers; only allow read-only inspect verbs.

    Image/container dictionaries are separate mutable snapshots. Neither docker()
    nor inventory construction inherits command/entrypoint via config.get(), so
    Compose null can never masquerade as a real Docker container's effective argv.
    """

    def __init__(self, rendered):
        config, self.host, self.ops, self.pointer = rendered
        self.config = deepcopy(config)
        self.calls = []
        services = config["services"]
        self.images = {}
        for role, digit in (("backend", "a"), ("db", "b"), ("redis", "c"), ("minio", "d"), ("frontend", "f")):
            entrypoint = APP_ENTRYPOINT if role == "backend" else ["docker-entrypoint.sh"]
            if role == "minio":
                entrypoint = ["/usr/bin/docker-entrypoint.sh"]
            elif role == "frontend":
                entrypoint = ["/docker-entrypoint.sh"]
            self.images[services[role]["image"]] = {
                "Id": "sha256:" + digit * 64,
                "RepoDigests": ["example.invalid/spaceworks/backend@" + DIGEST] if role == "backend" else [],
                "Config": {"Entrypoint": list(entrypoint),
                    "Cmd": list(APP_DEFAULT_CMD if role == "backend" else COMMANDS[role]),
                    "Env": ["PATH=/synthetic/image/bin", "IMAGE_DEFAULT=synthetic", "DEBUG=True"],
                    "Volumes": {"/data": {}} if role == "redis" else {}},
            }
        name = "9" * 64
        self.volume = {"Name": name, "Driver": "local", "Scope": "local", "Options": None,
            "Mountpoint": "/var/lib/docker/volumes/" + name + "/_data"}
        self.containers = {}
        for role in RUNNING:
            image = self.images[services[role]["image"]]
            env = dict(pair.split("=", 1) for pair in image["Config"]["Env"])
            env.update(services[role].get("environment", {}))
            self.containers[role] = {
                "Id": role, "Image": image["Id"], "State": {"Running": True},
                "Config": {"Labels": {"com.docker.compose.project": PROJECT,
                    "com.docker.compose.service": role, "com.docker.compose.oneoff": "False"},
                    "Entrypoint": list(APP_ENTRYPOINT) if role in APP_ROLES else list(image["Config"]["Entrypoint"]),
                    "Cmd": list(COMMANDS[role]), "Env": [key + "=" + value for key, value in env.items()]},
                "Mounts": self._mounts(role),
            }

    def _mounts(self, role):
        def bind(source, target, readonly=False):
            return {"Type": "bind", "Source": str(source), "Destination": target, "RW": not readonly}

        def volume(source, target):
            return {"Type": "volume", "Name": PROJECT + "_" + source,
                "Destination": target, "RW": True, "Driver": "local"}

        if role in APP_ROLES:
            mounts = [bind(self.host / "public", "/run/spaceworks-host", True),
                bind(self.ops / "work", "/var/lib/spaceworks/ops/work"),
                bind(self.ops / "operation.lock", "/var/lib/spaceworks/ops/operation.lock")]
            if role == "beat":
                mounts.append(volume("celerybeat_data", "/var/lib/celery"))
            else:
                mounts.append(bind(ROOT / "scripts", "/run/spaceworks-privileged-scripts", True))
            return mounts
        if role == "db":
            return [volume("makerspace_manager_pgdata", "/var/lib/postgresql/data"), bind(ROOT / "backups", "/backups")]
        if role == "redis":
            return [{"Type": "volume", "Name": self.volume["Name"], "Driver": "local", "RW": True,
                "Destination": "/data", "Source": self.volume["Mountpoint"]}]
        if role == "minio":
            return [volume("minio_data", "/data")]
        return []

    def docker(self, *args, json_result=False):
        self.calls.append(args)
        if args == ("ps", "-q", "--filter", "label=com.docker.compose.project=" + PROJECT):
            assert not json_result
            return "\n".join(self.containers)
        assert json_result
        if args[:2] == ("image", "inspect") and len(args) == 3:
            return [deepcopy(self.images[args[2]])]
        if args == ("volume", "inspect", self.volume["Name"]):
            return [deepcopy(self.volume)]
        if args[:1] == ("inspect",) and args[1:] == tuple(self.containers):
            return deepcopy(list(self.containers.values()))
        raise AssertionError("Unscripted Docker operation; no real daemon transport exists.")
