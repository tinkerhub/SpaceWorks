"""Updates bring an unedited deploy/Caddyfile up to the release and never clobber an edited one.

The TLS/SaaS overlays bind-mount these files into Caddy and no image carries them, so an
updated host used to keep its install-day proxy rules while a fresh install of the same
release got the new ones (for example the readiness/internal 403 rules).
"""

import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path("/workspace") if Path("/workspace/install.sh").exists() else Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout")
BASH = shutil.which("bash") or "bash"
HELPER = (ROOT / "scripts/refresh-proxy-config.sh").as_posix()


def shipped_digests():
    text = (ROOT / "scripts/refresh-proxy-config.sh").read_text()
    block = text.split("SHIPPED_PROXY_CONFIG_SHA256=(", 1)[1].split(")", 1)[0]
    return set(block.split())


def run_refresh(installed, staged, shipped_override=None):
    override = ""
    if shipped_override is not None:
        override = "SHIPPED_PROXY_CONFIG_SHA256=(" + " ".join(shipped_override) + ")"
    script = f'''set -euo pipefail
ROOT="$PWD"
say() {{ printf 'SAY %s\\n' "$*"; }}
warn() {{ printf 'WARN %s\\n' "$*"; }}
source '{HELPER}'
{override}
refresh_proxy_config "$1"
printf 'CHANGED=%s\\n' "$PROXY_CONFIG_CHANGED"
'''
    staged_shell = subprocess.check_output([BASH, "-c", "pwd"], cwd=staged, text=True).strip()
    return subprocess.run([BASH, "-c", script, "_", staged_shell], cwd=installed, capture_output=True, text=True)


def layout(tmp_path, installed_text, release_text="release rules\n"):
    installed, staged = tmp_path / "installed", tmp_path / "staged"
    for root in (installed, staged):
        (root / "deploy").mkdir(parents=True)
    (staged / "deploy/Caddyfile").write_text(release_text, encoding="utf-8", newline="\n")
    if installed_text is not None:
        (installed / "deploy/Caddyfile").write_text(installed_text, encoding="utf-8", newline="\n")
    return installed, staged


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize("name", ["deploy/Caddyfile", "deploy/Caddyfile.saas"])
def test_every_shipped_proxy_config_is_registered(name):
    # A new Caddyfile without its digest would make every unedited host look customised.
    digest = hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert digest in shipped_digests()


def test_unedited_shipped_file_is_replaced_and_backed_up(tmp_path):
    installed, staged = layout(tmp_path, "old shipped rules\n")
    result = run_refresh(installed, staged, [sha("old shipped rules\n")])
    assert result.returncode == 0, result.stderr
    assert "CHANGED=1" in result.stdout
    assert (installed / "deploy/Caddyfile").read_text() == "release rules\n"
    backups = list((installed / "backups").glob("proxy-config-*/deploy/Caddyfile"))
    assert [b.read_text() for b in backups] == ["old shipped rules\n"]


def test_edited_file_is_kept_with_release_copy_and_notice(tmp_path):
    installed, staged = layout(tmp_path, "my custom rules\n")
    result = run_refresh(installed, staged, [sha("old shipped rules\n")])
    assert result.returncode == 0, result.stderr
    assert "CHANGED=0" in result.stdout
    assert "WARN deploy/Caddyfile has local edits" in result.stdout
    assert (installed / "deploy/Caddyfile").read_text() == "my custom rules\n"
    assert (installed / "deploy/Caddyfile.release").read_text() == "release rules\n"


def test_identical_file_is_a_no_op_and_clears_a_stale_release_copy(tmp_path):
    installed, staged = layout(tmp_path, "release rules\n")
    (installed / "deploy/Caddyfile.release").write_text("stale\n", encoding="utf-8")
    result = run_refresh(installed, staged, [])
    assert result.returncode == 0, result.stderr
    assert "CHANGED=0" in result.stdout
    assert not (installed / "deploy/Caddyfile.release").exists()
    assert not (installed / "backups").exists()


def test_missing_file_is_installed(tmp_path):
    installed, staged = layout(tmp_path, None)
    result = run_refresh(installed, staged, [])
    assert result.returncode == 0, result.stderr
    assert (installed / "deploy/Caddyfile").read_text() == "release rules\n"


def test_updater_applies_proxy_config_on_update_and_on_already_installed():
    updater = (ROOT / "scripts/update.sh").read_text()
    assert 'source "$UPDATE_SCRIPT_DIR/refresh-proxy-config.sh"' in updater
    _, _, rest = updater.partition('say "$version is already installed."')
    assert 'apply_release_proxy_config "$tag"' in rest.split("exit 0", 1)[0]
    success = updater.split('say "Release update complete: $version."', 1)[1]
    assert success.lstrip().startswith('apply_release_proxy_config "$tag"')


def test_bulk_host_bundle_leaves_proxy_config_to_the_guarded_refresh():
    helper = (ROOT / "scripts/install-host-bundle.sh").read_text()
    file_list = helper.split("  local files=(", 1)[1].split("\n  )", 1)[0].split()
    assert "deploy/Caddyfile" not in file_list and "deploy/Caddyfile.saas" not in file_list
    assert "scripts/refresh-proxy-config.sh" in file_list


def test_installer_ensures_host_python3():
    # The Compose wrapper and setup run python3 on the host; minimal images lack it.
    installer = (ROOT / "install.sh").read_text()
    assert "for tool in curl tar python3; do" in installer
    assert "apt-get install -y curl tar python3" in installer
