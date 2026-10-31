"""Fixed synthetic inputs and secret-free Compose rendering (stdlib only)."""

import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess


PROFILES = {"base": "docker-compose.yml", "prod": "docker-compose.prod.yml", "cloud": "docker-compose.cloud.yml"}
# Public deterministic fixtures, copied by value rather than importing Django tests.
REQUIRED = {
    "POSTGRES_PASSWORD": "owner-password", "MINIO_ROOT_USER": "minio-user",
    "MINIO_ROOT_PASSWORD": "minio-password",
    "SECRET_KEY": "public-test-only-django-secret-at-least-32-characters",
    "ALLOWED_HOSTS": "localhost", "DATABASE_URL": "postgres://app@candidate/candidate",
    "SPACEWORKS_DB_POINTER_GENERATION": "4",
    "SPACEWORKS_MAINTENANCE_DATABASE_URL": "postgres://owner@candidate/candidate",
    "API_CLIENT_ENC_KEY": base64.urlsafe_b64encode(bytes(range(96, 128))).decode("ascii"),
    "AWS_ACCESS_KEY_ID": "access", "AWS_SECRET_ACCESS_KEY": "secret",
    "AWS_S3_ENDPOINT_URL": "https://storage.internal",
    "AWS_S3_PUBLIC_ENDPOINT_URL": "https://storage.example.test",
    "PUBLIC_APP_BASE_URL": "https://app.example.test",
    "PUBLIC_IMAGE_BASE_URL": "https://storage.example.test/public",
    "DEFAULT_FROM_EMAIL": "noreply@example.test",
}
MANAGE = '''import os
import sys

if sys.argv != ["manage.py", "collectstatic", "--noinput"]:
    raise SystemExit(24)
print("PROBE_COLLECTSTATIC", flush=True)
raise SystemExit(23 if os.environ.get("PROBE_COLLECTSTATIC_FAIL") == "1" else 0)
'''
WSGI = '''import json
import os

print("PROBE_WSGI_LOADED", flush=True)

def application(environ, start_response):
    body = json.dumps({"marker": "synthetic-worker-http", "worker_pid": os.getpid()}).encode()
    start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]
'''


class ProbeError(RuntimeError):
    """Messages are fixed stage labels, never subprocess output or environment."""


def require(condition, label):
    if not condition:
        raise ProbeError(label)


def run(argv, *, environment=None, cwd=None, timeout=20, check=True):
    try:
        result = subprocess.run(argv, env=environment, cwd=cwd, capture_output=True,
            text=True, timeout=timeout, check=False, close_fds=True)
    except (OSError, subprocess.TimeoutExpired):
        raise ProbeError("bounded subprocess unavailable or timed out") from None
    require(not check or result.returncode == 0, "subprocess refused (output withheld)")
    return result


def file_hashes(paths):
    return {label: hashlib.sha256(Path(path).read_bytes()).hexdigest() for label, path in paths.items()}


def write_probe(directory):
    directory.mkdir(mode=0o755)
    (directory / "config").mkdir(mode=0o755)
    files = {"manage.py": MANAGE, "config/__init__.py": "", "config/wsgi.py": WSGI}
    for name, body in files.items():
        path = directory / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o444)
    return {"probe/" + name: directory / name for name in files}


def render_commands(docker, root, private, plugin_directory=None):
    env_file = private / "synthetic.env"
    env_file.write_text("".join(f"{key}={value}\n" for key, value in REQUIRED.items()), encoding="utf-8")
    env_file.chmod(0o444)
    docker_config = private / "render-docker-config"
    docker_config.mkdir()
    config_file = docker_config / "config.json"
    config = {"cliPluginsExtraDirs": [str(plugin_directory.resolve())]} if plugin_directory else {}
    config_file.write_text(json.dumps(config) + "\n", encoding="utf-8")
    config_file.chmod(0o444)
    # Explicit env-file and -f disable implicit .env and machine override loading.
    # No HOME reassignment; a daemon request cannot reach the actual host socket.
    environment = {"PATH": os.environ.get("PATH", os.defpath),
        "DOCKER_CONFIG": str(docker_config),
        "DOCKER_HOST": "unix://" + str(private / "nonexistent-render.sock")}
    fixed = {"synthetic.env": env_file, "render-docker-config/config.json": config_file}
    env_hash = file_hashes(fixed)
    commands, config_hashes = {}, {}
    for profile, filename in PROFILES.items():
        result = run([docker, "compose", "--project-name", "backend-process-probe",
            "--project-directory", str(root), "--env-file", str(env_file),
            "--profile", "host-recovery", "-f", str(root / filename),
            "config", "--format", "json"], environment=environment, cwd=root, timeout=30)
        try:
            document = json.loads(result.stdout)
            command = document["services"]["backend"]["command"]
        except (ValueError, KeyError, TypeError):
            raise ProbeError("Compose backend JSON shape invalid") from None
        require(isinstance(command, list) and len(command) == 5
            and command[:4] == ["--role", "backend", "sh", "-c"]
            and isinstance(command[4], str), "Compose backend role/shell prefix changed")
        # Expectations are independent of admission and the production regex.
        expected = ["python", "manage.py", "collectstatic", "--noinput", "&&", "exec",
            "gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
        if profile != "base":
            expected += ["--workers", "3", "--timeout", "60", "--graceful-timeout", "30",
                "--max-requests", "1000", "--max-requests-jitter", "100",
                "--access-logfile", "-", "--error-logfile", "-"]
        lexer = shlex.shlex(command[4], posix=True, punctuation_chars=";&|")
        lexer.whitespace_split, lexer.commenters = True, ""
        require(list(lexer) == expected and "\n" not in command[4], "Compose backend argv changed")
        require(command[4].count("&& exec gunicorn") == 1, "Compose exec position changed")
        commands[profile] = command
        config_hashes[profile] = hashlib.sha256(result.stdout.encode()).hexdigest()
    require(file_hashes(fixed) == env_hash, "synthetic rendering inputs changed")
    return commands, config_hashes, fixed
