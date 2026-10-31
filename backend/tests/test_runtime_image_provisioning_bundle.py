"""Install the complete real runtime bundle into disposable, separate host roots."""

import ast
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[2]
HELPER = "scripts/provision-runtime-image.py"


def bundle_fixture(tmp_path):
    installer = (ROOT / "scripts/install-host-bundle.sh").read_text()
    fixed = installer.split("  local files=(", 1)[1].split("\n  )", 1)[0].split()
    tree = ast.parse((ROOT / "scripts/check-restore-host-bundle.py").read_text())
    declarations = [node.value for node in tree.body if isinstance(node, ast.Assign)
                    and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "REVIEWED_PATHS"]
    assert len(declarations) == 1
    reviewed = ast.literal_eval(declarations[0])
    assert isinstance(reviewed, tuple) and len(reviewed) == len(set(reviewed)) == 25
    files = [*fixed, *reviewed]
    assert len(fixed) == 35 and len(files) == len(set(files)) == 60
    assert HELPER in fixed
    staged, installed = tmp_path / "staged", tmp_path / "installed"
    staged.mkdir()
    installed.mkdir()
    previous = {}
    for relative in files:
        part = Path(relative)
        assert not part.is_absolute() and ".." not in part.parts
        source = staged / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, source)
        if relative != HELPER:
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            previous[relative] = b"old runtime: " + relative.encode() + b"\n"
            target.write_bytes(previous[relative])
    private = {
        "private.env": b"SECRET_KEY=synthetic-do-not-log\n",
        ".env": b"PRIVATE_CONFIGURATION=preserve\n",
        "host/authority/private.key": b"private authority sentinel\x00\n",
        "host/public/producer-capability.json": b"authority proof sentinel\n",
        "backups/existing.dump": b"existing backup sentinel\x00",
        "data/sentinel.bin": b"durable data sentinel\x00",
    }
    for relative, value in private.items():
        target = installed / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
        target.chmod(0o600)
    return staged, installed, files, previous, private


def snapshot(root):
    return {path.relative_to(root).as_posix():
            (path.read_bytes(), path.stat().st_ino, stat.S_IMODE(path.stat().st_mode))
            for path in root.rglob("*") if path.is_file()}


def install(staged, installed):
    script = f'''set -euo pipefail
ROOT="$PWD"
say() {{ printf '%s\\n' "$*"; }}
die() {{ printf '%s\\n' "$*" >&2; exit 1; }}
source {shlex.quote(str(ROOT / 'scripts/install-host-bundle.sh'))}
install_staged_host_bundle {shlex.quote(str(staged))}
'''
    assert staged != installed
    return subprocess.run(["bash", "-c", script], cwd=installed,
                          env={"PATH": os.environ["PATH"], "LC_ALL": "C"},
                          capture_output=True, text=True, timeout=30)


def test_actual_bundle_installs_provisioner_and_all_60_files_preserving_private_state(tmp_path):
    staged, installed, files, previous, private = bundle_fixture(tmp_path)
    before = snapshot(installed)
    result = install(staged, installed)
    assert result.returncode == 0, result.stderr
    for relative in files:
        target = installed / relative
        info = target.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert stat.S_IMODE(info.st_mode) == (0o755 if relative.endswith(".sh") else 0o644)
        assert target.read_bytes() == (ROOT / relative).read_bytes()
    assert (installed / HELPER).read_bytes() == (ROOT / HELPER).read_bytes()
    assert stat.S_IMODE((installed / HELPER).stat().st_mode) == 0o644
    backups = list((installed / "backups").glob("host-config-*"))
    assert len(backups) == 1
    assert {path.relative_to(backups[0]).as_posix(): path.read_bytes()
            for path in backups[0].rglob("*") if path.is_file()} == previous
    after = snapshot(installed)
    for relative, value in private.items():
        assert after[relative] == before[relative]
        assert after[relative][0] == value
    assert not list(installed.rglob(".deploy-bundle.*"))
    assert "synthetic-do-not-log" not in result.stdout + result.stderr


def test_actual_bundle_refuses_only_missing_provisioner_before_any_destination_write(tmp_path):
    staged, installed, files, _, _ = bundle_fixture(tmp_path)
    (staged / HELPER).unlink()
    assert {path.relative_to(staged).as_posix() for path in staged.rglob("*")
            if path.is_file()} == set(files) - {HELPER}
    for relative in set(files) - {HELPER}:
        assert (staged / relative).read_bytes() == (ROOT / relative).read_bytes()
    before = snapshot(installed)
    directories = {path.relative_to(installed) for path in installed.rglob("*") if path.is_dir()}
    result = install(staged, installed)
    assert result.returncode != 0
    assert "The pinned archive lacks a regular scripts/provision-runtime-image.py." in result.stderr
    assert snapshot(installed) == before
    assert {path.relative_to(installed) for path in installed.rglob("*") if path.is_dir()} == directories
    assert not (installed / HELPER).exists()
    assert not list((installed / "backups").glob("host-config-*"))
    assert not list(installed.rglob(".deploy-bundle.*"))
    assert "Installed pinned host runtime files" not in result.stdout
    assert "synthetic-do-not-log" not in result.stdout + result.stderr
