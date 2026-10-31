"""Copied pinned runtime only: no import or PYTHONPATH fallback to checkout."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from tests.backup.recovery_test_support import repo_root, require_linux_root


def inventory():
    data = json.loads((repo_root() / "docs/audits/2026-10-29/evidence/recovery-final-source-freeze.json").read_bytes())
    files = data["pinned_runtime_copy_files"]
    assert len(files) == 60 and len({item["path"] for item in files}) == 60
    assert any(item["path"] == "scripts/provision-runtime-image.py" and item["installed_mode"] == "0644" for item in files)
    return files


def copy_bundle(destination):
    for fact in inventory():
        source = repo_root() / fact["path"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == fact["sha256"], fact["path"]
        target = destination / fact["path"]
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(int(fact["installed_mode"], 8))
    for directory in destination.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o755)
    destination.chmod(0o755)
    return destination


@contextmanager
def installed_root():
    require_linux_root()
    # Standard pytest --basetemp may be under an operator-owned ancestor. The
    # production wrapper intentionally allows only root-owned sticky /tmp here.
    with tempfile.TemporaryDirectory(prefix="recovery-installed-", dir="/tmp") as value:
        root = copy_bundle(Path(value))
        yield root


def run_wrapper(root, *args, nonroot=False):
    options = {"user": 65534, "group": 65534, "extra_groups": []} if nonroot else {}
    return subprocess.run(["bash", str(root / "scripts/restore.sh"), *map(str, args)],
        cwd="/", env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/must-not-be-used"},
        capture_output=True, text=True, close_fds=True, timeout=20, **options)


def snapshot(root):
    return {str(path.relative_to(root)): (path.stat().st_mode & 0o777, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in root.rglob("*") if path.is_file()}


def install(source, target, *, nonroot=False):
    code = '''set -euo pipefail
die() { echo "$*" >&2; exit 31; }
say() { :; }
ROOT="$1"
source "$3"
install_staged_host_bundle "$2"
'''
    options = {"user": 65534, "group": 65534, "extra_groups": []} if nonroot else {}
    # The updater has already loaded trusted installed helper code; staged inputs
    # (including a broken copy of that helper) are only preflight data here.
    with tempfile.TemporaryDirectory(prefix="recovery-installed-caller-", dir="/tmp") as directory:
        caller = Path(directory)
        caller.chmod(0o755)
        helper = caller / "install-host-bundle.sh"
        helper.write_bytes((repo_root() / "scripts/install-host-bundle.sh").read_bytes())
        helper.chmod(0o644)
        return subprocess.run(["bash", "-c", code, "private-stage3", str(target), str(source), str(helper)], cwd="/",
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"}, capture_output=True, text=True, timeout=30,
            close_fds=True, **options)
