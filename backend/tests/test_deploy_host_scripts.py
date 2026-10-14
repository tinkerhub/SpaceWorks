"""Exercise the host queue consumer and release bundle without Docker or systemd."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path("/workspace") if Path("/workspace/install.sh").exists() else Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout")
BASH = shutil.which("bash") or "bash"


def executable(path, source):
    path.write_text(source, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def shell_path(path):
    return subprocess.check_output([BASH, "-c", "pwd"], cwd=path, text=True).strip()


def test_consumer_never_uses_payload_and_preserves_arrivals_during_update(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    queue = tmp_path / "ops/deploy-requests"
    queue.mkdir(parents=True)
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("deploy-from-request.sh", "env-file.sh"):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    root = shell_path(tmp_path)
    (tmp_path / ".env").write_text(f"SPACEWORKS_OPS_HOST_DIR={root}/ops\n", encoding="utf-8")
    request = queue / "original.json"
    request.write_text('{"tag":"$(touch payload-executed)"}', encoding="utf-8")
    executable(scripts / "update.sh", '''#!/bin/bash
printf '%s|%s\n' "$SPACEWORKS_DEPLOY_WAIT" "$*" >> "$CALLS"
if [[ ! -f "$ATTEMPT" ]]; then touch "$ATTEMPT"; exit 75; fi
touch "$ARRIVAL"
echo 0.9.0-main.2.bbbbbbbbbbbb > .spaceworks-version
''')
    executable(tools / "sleep", "#!/bin/sh\nexit 0\n")
    calls = tmp_path / "calls"
    result = subprocess.run([BASH, str(scripts / "deploy-from-request.sh")], cwd=tmp_path,
                            env={**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
                                 "SPACEWORKS_OPS_HOST_DIR": "", "CALLS": f"{root}/calls",
                                 "ATTEMPT": f"{root}/attempt", "ARRIVAL": f"{root}/ops/deploy-requests/new.json"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    # No --force: a delivery deploys only a release newer than the installed one.
    assert calls.read_text().splitlines() == ["1|--no-module-changes"] * 2
    assert not request.exists()
    assert (queue / "new.json").exists()
    assert not (tmp_path / "payload-executed").exists()
    assert not (tmp_path / ".spaceworks-deploy.lock").exists()


def _consume_once(tmp_path, update_body):
    """Run the consumer once against a fake updater; returns (result, queue dir)."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    queue = tmp_path / "ops/deploy-requests"
    queue.mkdir(parents=True)
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("deploy-from-request.sh", "env-file.sh"):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    root = shell_path(tmp_path)
    (tmp_path / ".env").write_text(f"SPACEWORKS_OPS_HOST_DIR={root}/ops\n", encoding="utf-8")
    (tmp_path / ".spaceworks-version").write_text("0.9.0-main.1.aaaaaaaaaaaa\n", encoding="utf-8")
    for name, run in (("reached", 2), ("fresh", 3), ("stale", 3)):
        (queue / f"{name}.json").write_text(
            f'{{"tag": "v0.9.0-main.{run}.cccccccccccc", "delivery": "{name}"}}\n', encoding="utf-8")
    stale = queue / "stale.json"
    old = stale.stat().st_mtime - 2 * 24 * 3600
    os.utime(stale, (old, old))
    executable(scripts / "update.sh", "#!/bin/bash\n" + update_body)
    executable(tools / "sleep", "#!/bin/sh\nexit 0\n")
    result = subprocess.run([BASH, str(scripts / "deploy-from-request.sh")], cwd=tmp_path,
                            env={**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
                                 "SPACEWORKS_OPS_HOST_DIR": ""},
                            capture_output=True, text=True, timeout=30)
    return result, queue


def test_a_delivery_before_promotion_is_kept_for_a_later_run(tmp_path):
    # update.sh found nothing newer than the installed release: "latest" not promoted yet.
    result, queue = _consume_once(tmp_path, "exit 0\n")
    assert result.returncode == 0, result.stderr
    assert (queue / "fresh.json").exists()
    assert not (queue / "stale.json").exists()


def test_a_host_catching_up_keeps_requests_for_releases_it_has_not_reached(tmp_path):
    # A host that was behind installs the previous "latest" (run 2) before run 3 is promoted.
    result, queue = _consume_once(
        tmp_path, "echo 0.9.0-main.2.bbbbbbbbbbbb > .spaceworks-version\n")
    assert result.returncode == 0, result.stderr
    assert not (queue / "reached.json").exists()
    assert (queue / "fresh.json").exists()


def test_a_failed_update_keeps_the_request_for_retry(tmp_path):
    result, queue = _consume_once(tmp_path, "exit 1\n")
    assert result.returncode == 1
    assert (queue / "fresh.json").exists()
    # Two days old is past the one-day failure window, so it is dropped, not retried forever.
    assert not (queue / "stale.json").exists()


def test_retire_tombstone_preserves_surviving_tokens_and_cleans_shell(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("OTHER=value\n export TOMBSTONED_APPS='payments, updates, mobile'\n", encoding="utf-8")
    script = f'''set -e
ROOT="$PWD"
source '{ROOT.as_posix()}/scripts/env-file.sh'
source '{ROOT.as_posix()}/scripts/retire-update-tombstone.sh'
TOMBSTONED_APPS='updates,payments'
retire_update_tombstone
printf '%s' "$TOMBSTONED_APPS"
'''
    result = subprocess.run([BASH, "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "payments"
    assert "OTHER=value" in dotenv.read_text()
    assert "TOMBSTONED_APPS=payments, mobile" in dotenv.read_text()
    assert "updates" not in dotenv.read_text()


def test_staged_bundle_adopts_runtime_files_and_preserves_private_state(tmp_path):
    installed = tmp_path / "installed"
    staged = tmp_path / "staged"
    installed.mkdir()
    staged.mkdir()
    helper = (ROOT / "scripts/install-host-bundle.sh").read_text()
    file_list = helper.split("  local files=(", 1)[1].split("\n  )", 1)[0].split()
    assert "backend/scripts/deploy_webhook.py" in file_list
    for relative in file_list:
        path = staged / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"new {relative}\n", encoding="utf-8")
    (installed / "setup.sh").write_text("old setup\n", encoding="utf-8")
    (installed / "scripts").mkdir()
    (installed / "scripts/install-auto-update.sh").write_text("old poller\n", encoding="utf-8")
    for name in (".env", ".spaceworks-version", ".spaceworks-layer"):
        (installed / name).write_text(f"private {name}\n", encoding="utf-8")
    script = f'''set -e
ROOT="$PWD"
say() {{ :; }}
die() {{ echo "$*" >&2; exit 1; }}
source '{ROOT.as_posix()}/scripts/install-host-bundle.sh'
install_staged_host_bundle '{shell_path(staged)}'
'''
    result = subprocess.run([BASH, "-c", script], cwd=installed, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for relative in file_list:
        assert (installed / relative).read_bytes() == (staged / relative).read_bytes()
    assert not (installed / "scripts/install-auto-update.sh").exists()
    backups = list((installed / "backups").glob("host-config-*"))
    assert len(backups) == 1
    assert (backups[0] / "setup.sh").read_text() == "old setup\n"
    assert (backups[0] / "scripts/install-auto-update.sh").read_text() == "old poller\n"
    for name in (".env", ".spaceworks-version", ".spaceworks-layer"):
        assert (installed / name).read_text() == f"private {name}\n"


def test_bundle_refuses_missing_file_before_replacing_anything(tmp_path):
    installed = tmp_path / "installed"
    staged = tmp_path / "staged"
    installed.mkdir()
    staged.mkdir()
    (installed / "setup.sh").write_text("old setup\n", encoding="utf-8")
    script = f'''set -e
ROOT="$PWD"
say() {{ :; }}
die() {{ echo "$*" >&2; exit 1; }}
source '{ROOT.as_posix()}/scripts/install-host-bundle.sh'
install_staged_host_bundle '{shell_path(staged)}'
'''
    result = subprocess.run([BASH, "-c", script], cwd=installed, capture_output=True, text=True)
    assert result.returncode != 0
    assert (installed / "setup.sh").read_text() == "old setup\n"
    assert not (installed / "backups").exists()


def test_layer_marker_and_queue_permissions_are_kept_for_host_trigger():
    wrapper = (ROOT / "scripts/spaceworks-compose.sh").read_text()
    installer = (ROOT / "scripts/install-deploy-webhook.sh").read_text()
    prepare = (ROOT / "scripts/setup-host-orchestration.sh").read_text()
    assert '.spaceworks-layer' in wrapper and '.spaceworks-layer' in installer
    assert 'chown 10001:$host_gid /ops/deploy-requests' in prepare
    assert 'chmod 2770 /ops/deploy-requests' in prepare
    assert 'PathExistsGlob=$REQUEST_DIR/*.json' in installer
    assert 'User=$owner' in installer
    assert 'ExecStart=/bin/bash "$ROOT/scripts/deploy-from-request.sh"' in installer


@pytest.mark.parametrize("leftover", ["ownerless", "legacy-dead-pid"])
def test_deploy_wait_never_hangs_on_an_unowned_lock(tmp_path, leftover):
    lock = tmp_path / ".spaceworks-update.lock"
    lock.mkdir()
    if leftover == "legacy-dead-pid":
        (lock / "pid").write_text("999999\n", encoding="utf-8")
    script = f'''set -e
say() {{ :; }}
die() {{ echo "$*" >&2; exit 1; }}
LOCK_DIR='{shell_path(tmp_path)}/.spaceworks-update.lock'
OPS_DIR='{shell_path(tmp_path)}/ops'
SPACEWORKS_DEPLOY_WAIT=1
source '{ROOT.as_posix()}/scripts/update-lock.sh'
acquire_update_lock
'''
    # Before the fix this looped forever on a lock with no readable live owner.
    result = subprocess.run([BASH, "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    if leftover == "ownerless":
        assert result.returncode != 0 and "no readable owner" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
