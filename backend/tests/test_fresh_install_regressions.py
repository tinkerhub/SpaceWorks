"""Regressions found by running the real installer on a clean Debian 13 host.

Each test pins one failure a brand-new operator hit: an API that answered 502 right after
install, updates that died on a root-owned backups/ directory, .env keys that never reached
Django, and secrets missing from an older .env.
"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path("/workspace") if Path("/workspace/install.sh").exists() else Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout")
BASH = shutil.which("bash") or "bash"


def compose(name):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["docker-compose.prod.yml", "docker-compose.cloud.yml", "docker-compose.yml"])
def test_frontend_restarts_when_compose_recreates_backend(name):
    # nginx resolves `backend` once. setup.sh recreates backend after writing the backup
    # keys, so without this the fresh install served 502 for every /api call.
    backend_dep = compose(name)["services"]["frontend"]["depends_on"]["backend"]
    assert backend_dep == {"condition": "service_healthy", "restart": True}


FORWARDED = (
    "CHECKIN_PROVIDER_NAME", "EVENT_STATION_PIN_PEPPER", "PUSH_TOKEN_HMAC_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET", "GITHUB_API_TOKEN",
    "STRIPE_CONNECT_REDIRECT_URI", "PUBLIC_IMAGE_MAX_BYTES", "PUBLIC_IMAGE_URL_TTL_SECONDS",
    "PLATFORM_STAFF_ORIGINS",
)
CLOUD_ONLY = (
    "CRON_SECRET", "SECURE_HSTS_SECONDS", "AWS_S3_REGION_NAME", "TELEGRAM_API_URL",
    "AUTH_COOKIE_SAMESITE", "AUTH_COOKIE_SECURE",
)


@pytest.mark.parametrize(
    ("name", "services", "keys"),
    [
        ("docker-compose.prod.yml", ("backend", "migrate", "worker", "beat"), FORWARDED),
        ("docker-compose.cloud.yml", ("backend", "migrate", "cron"), FORWARDED + CLOUD_ONLY),
    ],
)
def test_operator_settings_reach_every_django_process(name, services, keys):
    document = compose(name)["services"]
    for service in services:
        environment = document[service].get("environment") or {}
        missing = [key for key in keys if key not in environment]
        assert not missing, f"{name}:{service} does not forward {missing}"


def test_setup_creates_backups_before_docker_can_create_it_as_root():
    setup = (ROOT / "setup.sh").read_text()
    assert setup.index("mkdir -p backups && chmod 700 backups") < setup.index('"${COMPOSE[@]}" pull')


def run_update_with_foreign_backups(tmp_path):
    """Run only update.sh's ownership repair against a backups/ we do not own."""
    updater = (ROOT / "scripts/update.sh").read_text()
    start = updater.index('if [[ -d "$ROOT/backups" && ! -O "$ROOT/backups" ]]; then')
    block = updater[start:updater.index("\nfi\n", start) + 4]
    (tmp_path / "backups").mkdir()
    calls = tmp_path / "calls"
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "docker").write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{calls.as_posix()}"\n', newline="\n")
    (fake / "docker").chmod(0o755)
    script = f'''set -euo pipefail
ROOT="$PWD"; BACKEND_IMAGE=example/backend
die() {{ echo "$*" >&2; exit 1; }}
resolve_image_tag() {{ echo 1.0.0; }}
{block.replace('! -O "$ROOT/backups"', '1 == 1')}
'''
    env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run([BASH, "-c", script], cwd=tmp_path, capture_output=True, text=True, env=env)
    return result, calls.read_text() if calls.exists() else ""


def test_update_repairs_a_root_owned_backups_directory(tmp_path):
    result, calls = run_update_with_foreign_backups(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--user 0:0 --entrypoint chown" in calls and "example/backend:1.0.0" in calls
    assert "/backups:/b" in calls


def test_update_creates_backups_before_starting_db():
    updater = (ROOT / "scripts/update.sh").read_text()
    assert updater.index('chmod 700 "$ROOT/backups"') < updater.index('"${COMPOSE[@]}" up -d --wait db')


def backfill(tmp_path, dotenv):
    setup = (ROOT / "setup.sh").read_text()
    start = setup.index("AUDIT_KEY_ADDED=0")
    block = setup[start:setup.index("\ndone\n", start) + 6]
    (tmp_path / ".env").write_text(dotenv, encoding="utf-8", newline="\n")
    script = f'''set -euo pipefail
die() {{ echo "$*" >&2; exit 1; }}
source '{(ROOT / "scripts/env-file.sh").as_posix()}'
fernet_key() {{ echo GENERATED-KEY; }}
{block}
echo "ADDED=$AUDIT_KEY_ADDED"
'''
    result = subprocess.run([BASH, "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout, (tmp_path / ".env").read_text()


def test_setup_backfills_missing_and_empty_encryption_keys(tmp_path):
    out, dotenv = backfill(tmp_path, "SECRET_KEY=x\nAUDIT_MAC_MASTER_KEY=\n")
    assert "ADDED=1" in out
    assert dotenv.count("API_CLIENT_ENC_KEY=GENERATED-KEY") == 1
    assert dotenv.count("AUDIT_MAC_MASTER_KEY=") == 1
    assert "AUDIT_MAC_MASTER_KEY=GENERATED-KEY" in dotenv


def test_setup_never_changes_an_existing_encryption_key(tmp_path):
    original = "API_CLIENT_ENC_KEY=keep-me\nAUDIT_MAC_MASTER_KEY=keep-too\n"
    out, dotenv = backfill(tmp_path, original)
    assert "ADDED=0" in out
    assert dotenv == original
