"""Exercise the release bundle and host update lock without Docker or systemd."""

import ast
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


def reviewed_restore_paths():
    """Read the checker's fixed closure as data, without importing host code."""
    tree = ast.parse((ROOT / "scripts/check-restore-host-bundle.py").read_text(encoding="utf-8"))
    declarations = [node for node in tree.body if isinstance(node, ast.Assign)
                    and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "REVIEWED_PATHS"]
    assert len(declarations) == 1
    literal = declarations[0].value
    assert isinstance(literal, ast.Tuple)
    assert all(isinstance(node, ast.Constant) and isinstance(node.value, str)
               for node in literal.elts)
    paths = ast.literal_eval(literal)
    assert len(paths) == len(set(paths)) == 25
    for relative in paths:
        path = Path(relative)
        assert not path.is_absolute() and ".." not in path.parts
        assert path.as_posix() == relative and relative != "."
    return paths


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


@pytest.mark.parametrize("prefix", ["", "  ", "\t", "export ", "\texport "],
                         ids=["bare", "spaces", "tab", "export", "tab-export"])
def test_retire_tombstone_portable_assignments_are_atomic_and_idempotent(tmp_path, prefix):
    dotenv = tmp_path / ".env"
    preserved = (
        "# Legacy TOMBSTONED_APPS=updates comment\n"
        "OTHER=legacy-value\nAUTO_UPDATE_ENABLED=1\nUPDATE_INTERVAL=900\n"
        'LITERAL="TOMBSTONED_APPS=updates"\n'
    )
    original = preserved + f"{prefix}TOMBSTONED_APPS='payments , updates, mobile, updates , accounts'\n"
    dotenv.write_text(original, encoding="utf-8")
    dotenv.chmod(0o644)
    expected = preserved + "\nTOMBSTONED_APPS=payments , mobile, accounts\n"
    script = f'''set -e
ROOT="$PWD"
source '{ROOT.as_posix()}/scripts/env-file.sh'
source '{ROOT.as_posix()}/scripts/retire-update-tombstone.sh'
TOMBSTONED_APPS='updates, payments ,updates, mobile, updates ,accounts'
for pass in 1 2; do
  retire_update_tombstone
  [[ "$TOMBSTONED_APPS" == ' payments , mobile,accounts' ]]
done
[[ "$(env_file_get "$ROOT/.env" TOMBSTONED_APPS)" == 'payments , mobile, accounts' ]]
printf 'cleanup-ok\n'
'''
    # Keep the old inode open: replacement must leave its contents untouched.
    with dotenv.open("rb") as previous:
        old_stat = os.fstat(previous.fileno())
        replacement_stat = None
        for _ in range(2):
            result = subprocess.run(
                [BASH, "-c", script], cwd=tmp_path, capture_output=True, text=True,
                env={"PATH": os.defpath, "LC_ALL": "C"}, timeout=10,
            )
            assert result.returncode == 0, "tombstone cleanup failed"
            assert result.stdout == "cleanup-ok\n"
            assert result.stderr == ""
            contents = dotenv.read_text(encoding="utf-8")
            assert contents == expected
            assignments = [line.lstrip().removeprefix("export ") for line in contents.splitlines()]
            assert sum(line.startswith("TOMBSTONED_APPS=") for line in assignments) == 1
            current_stat = dotenv.stat()
            assert current_stat.st_mode & 0o777 == 0o600
            assert current_stat.st_ino != old_stat.st_ino
            assert set(tmp_path.iterdir()) == {dotenv}
            if replacement_stat is not None:
                assert current_stat.st_ino == replacement_stat.st_ino
                assert current_stat.st_mtime_ns == replacement_stat.st_mtime_ns
            replacement_stat = current_stat
        assert previous.read() == original.encode("utf-8")


def test_staged_bundle_adopts_runtime_files_and_preserves_private_state(tmp_path):
    installed = tmp_path / "installed"
    staged = tmp_path / "staged"
    installed.mkdir()
    staged.mkdir()
    helper = (ROOT / "scripts/install-host-bundle.sh").read_text()
    file_list = helper.split("  local files=(", 1)[1].split("\n  )", 1)[0].split()
    assert "scripts/install-deploy-runner.sh" in file_list
    assert "scripts/setup-deploy-runner.sh" in file_list
    file_list.extend(reviewed_restore_paths())
    for relative in file_list:
        path = staged / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the real preflight checker and restore.sh digest authority enabled.
        shutil.copyfile(ROOT / relative, path)
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


def test_layer_marker_is_kept_for_host_updates():
    wrapper = (ROOT / "scripts/spaceworks-compose.sh").read_text()
    updater = (ROOT / "scripts/update.sh").read_text()
    assert '.spaceworks-layer' in wrapper and '.spaceworks-layer' in updater


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
