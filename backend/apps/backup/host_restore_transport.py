"""Root-only bounded Compose transport; children never inherit the operation lock."""

import json
import os
from pathlib import Path
import subprocess
import uuid

from .host_pointer import read_pointer
from .host_topology_record import validate_compose_wrapper
from .host_private_file import write_private_file_fsynced


class RestoreHostError(RuntimeError):
    pass


LAYERS = {
    "none": (), "build": ("build",), "tls": ("tls",),
    "build-tls": ("build", "tls"), "saas": ("saas",),
    "build-saas": ("build", "saas"),
}


def private_json(path, value):
    write_private_file_fsynced(path, json.dumps(value, sort_keys=True) + "\n")


def trusted(path, *, private=False, directory=False):
    import stat

    path = Path(path)
    info = path.stat(follow_symlinks=False)
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid_type or info.st_uid != 0 or info.st_mode & (0o077 if private else 0o022):
        raise RestoreHostError("An installed host authority input is untrusted.")
    for parent in path.absolute().parents:
        ancestor = parent.stat(follow_symlinks=False)
        sticky_root = ancestor.st_uid == 0 and bool(ancestor.st_mode & stat.S_ISVTX)
        if (not stat.S_ISDIR(ancestor.st_mode) or ancestor.st_uid != 0
                or (ancestor.st_mode & 0o022 and not sticky_root)):
            raise RestoreHostError("A host authority path has an untrusted directory ancestor.")
    return path


class RestoreTransport:
    def __init__(self, root):
        self.root = Path(root).resolve()
        trusted(self.root, directory=True)
        trusted(self.root / "scripts/spaceworks-compose.sh")
        trusted(self.root / "scripts/validate-compose-wrapper.py")
        self.static_env = trusted(self.root / ".env", private=True)
        # Host controls come from installed files, never arbitrary shell interpolation.
        from .host_restore_configuration import read_controls

        controls = read_controls(self.static_env)
        self.ops = Path(controls.get("SPACEWORKS_OPS_HOST_DIR", "/var/lib/spaceworks/ops"))
        self.host = Path(controls.get("SPACEWORKS_HOST_STATE_DIR", "/var/lib/spaceworks/host"))
        trusted(self.ops, directory=True)
        trusted(self.host / "public", directory=True)
        for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH",
                     "DOCKER_CONFIG", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME"):
            if os.environ.get(name):
                raise RestoreHostError("Inherited Docker/Compose endpoint or project overrides are unsupported.")
        layer_path = self.root / ".spaceworks-layer"
        layer = trusted(layer_path).read_text().strip() if layer_path.exists() else "none"
        if layer not in LAYERS:
            raise RestoreHostError("The installed Compose layer is unsupported.")
        self.layer = layer
        self.files = [self.root / "docker-compose.prod.yml"] + [
            self.root / "docker" / f"compose.{name}.yml" for name in LAYERS[layer]
        ]
        for path in self.files:
            trusted(path)
        suffix = "" if layer == "none" else f"-{layer}"
        self.record = self.ops / f"compose-topology{suffix}.json"
        self.pointer = read_pointer(self.ops / "database-pointer.env")
        self.environment = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                            "HOME": "/root", "LANG": "C.UTF-8", "DOCKER_CONTEXT": "default",
                            "SPACEWORKS_OPS_HOST_DIR": str(self.ops),
                            "SPACEWORKS_STATIC_ENV_FILE": str(self.static_env),
                            "SPACEWORKS_COMPOSE_LAYER": layer}
        version = self.root / ".spaceworks-version"
        if version.exists() and not any(line.startswith("MAKERSPACE_IMAGE_TAG=") and bool(line.split("=", 1)[1])
                for line in self.static_env.read_text().splitlines()):
            import re
            pinned = trusted(version).read_text().strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", pinned):
                raise RestoreHostError("Installed image version is invalid.")
            self.environment["MAKERSPACE_IMAGE_TAG"] = pinned
        # No inherited SSH/remote daemon/context substitution is admitted.
        endpoint = self.docker("context", "inspect", "default", json_result=True)
        if endpoint[0]["Endpoints"]["docker"]["Host"] != "unix:///var/run/docker.sock":
            raise RestoreHostError("Only the installed local bundled Docker endpoint is supported.")
        self.facts = self.validate()
        self.config = self.compose("config", "--format", "json", json_result=True)

    def validate(self):
        return validate_compose_wrapper(topology="bundled", static_env=self.static_env,
            pointer_file=self.ops / "database-pointer.env", topology_record=self.record,
            compose_files=self.files)

    def execute(self, argv, *, input_bytes=None, input_file=None, json_result=False, output=None):
        result = subprocess.run(argv, cwd=self.root, env=self.environment, input=input_bytes, stdin=input_file,
            stdout=output if output is not None else subprocess.PIPE,
            stderr=subprocess.PIPE, close_fds=True, check=False)
        if result.returncode:
            # Compose errors can contain interpolated secrets. Retain no raw stderr.
            raise RestoreHostError("A fixed host restore transport command failed; authority remains blocked.")
        if output is not None:
            output.flush()
            os.fsync(output.fileno())
            return None
        if json_result:
            try:
                return json.loads(result.stdout)
            except (ValueError, UnicodeError) as exc:
                raise RestoreHostError("A fixed restore probe returned malformed evidence.") from exc
        return result.stdout.decode("utf-8").strip()

    def compose(self, *args, **kwargs):
        if args and args[0] in {"run", "up"}:
            if not getattr(self, "admitted_image_id", None):
                raise RestoreHostError("A fixed image transport has not been admitted.")
            image = self.docker("image", "inspect", self.config["services"]["backend"]["image"], json_result=True)[0]
            if (image["Id"] != self.admitted_image_id or not any(
                    item.endswith("@" + self.admitted_digest) for item in image.get("RepoDigests", []))):
                raise RestoreHostError("The admitted local image identity changed before a fixed launch.")
            args = (args[0], "--pull", "never", *args[1:])
        oneoff = "spaceworks-inplace-" + str(uuid.uuid4()) if args and args[0] == "run" else None
        if oneoff:
            args = (args[0], "--name", oneoff, *args[1:])
        try:
            return self.execute([str(self.root / "scripts/spaceworks-compose.sh"), "bundled", *args], **kwargs)
        finally:
            if oneoff:
                self._finish_oneoff(oneoff)

    def _finish_oneoff(self, name):
        ids = self.docker("ps", "-a", "-q", "--filter", f"name=^/{name}$").splitlines()
        if not ids:
            return
        containers = self.docker("inspect", *ids, json_result=True)
        if (len(containers) != 1 or containers[0]["Image"] != self.admitted_image_id
                or containers[0]["Config"].get("Labels", {}).get("com.docker.compose.project") != self.config["name"]):
            raise RestoreHostError("A fixed management one-off no longer matches its tracked identity.")
        if containers[0]["State"]["Running"]:
            self.docker("stop", ids[0])
        self.docker("rm", ids[0])

    def docker(self, *args, **kwargs):
        return self.execute(["docker", "--context", "default", *args], **kwargs)

    def control(self, *args, **kwargs):
        return self.compose("run", "--rm", "--no-deps", "-T", "backend", "--role",
                            "management", "python", "manage.py", "backup_control", *args, **kwargs)

    def app_path(self, path):
        return "/var/lib/spaceworks/ops/work/" + str(Path(path).relative_to(self.ops / "work"))

    def sql(self, command, *, input_bytes=None, input_file=None, output=None):
        return self.compose("exec", "-T", "db", "sh", "-c", command,
                            input_bytes=input_bytes, input_file=input_file, output=output)

    def grants(self, *, identity=None, temporary_database=None, legacy=False):
        args = ["run", "--rm", "--no-deps", "-T", "-e", "SPACEWORKS_GRANTS_ONLY=1"]
        if identity is not None:
            args += ["-e", "SPACEWORKS_RESTORE_IDENTITY=1"]
        if legacy:
            args += ["-e", "SPACEWORKS_RESTORE_LEGACY_IDENTITY=1"]
        if temporary_database:
            args += ["-e", f"SPACEWORKS_GRANT_DATABASE_NAME={temporary_database}"]
        return self.compose(*args, "orchestration-ready", input_bytes=identity)
