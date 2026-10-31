"""Real bounded bundle installer; staged source remains unexecuted until preflight."""

import hashlib
import os
from pathlib import Path

import pytest

from tests.backup.recovery_bundle_support import install, installed_root, inventory, snapshot
from tests.backup.recovery_test_support import require_linux_root


def sentinels(target):
    for name in (".env", "ops/private/authority", "keys/private-key", "backups/existing", "data/persistent"):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("retained-private-" + name).encode())
        path.chmod(0o600)


def test_actual_installer_copies_exact_reviewed_files_preserves_private_state_and_backups(tmp_path):
    require_linux_root()
    with installed_root() as source:
        target = tmp_path / "target"
        target.mkdir(mode=0o755)
        sentinels(target)
        (target / "scripts").mkdir()
        old = target / "scripts/restore.sh"
        old.write_bytes(b"previous installed wrapper\n")
        old.chmod(0o755)
        private_before = snapshot(target)
        result = install(source, target)
        assert result.returncode == 0, result.stderr
        expected = {fact["path"]: fact for fact in inventory()}
        for relative, fact in expected.items():
            path = target / relative
            assert hashlib.sha256(path.read_bytes()).hexdigest() == fact["sha256"], relative
            assert path.stat().st_uid == 0 and path.stat().st_gid == 0
            assert path.stat().st_mode & 0o777 == int(fact["installed_mode"], 8)
        for relative, fact in private_before.items():
            if relative != "scripts/restore.sh":
                assert snapshot(target)[relative] == fact
        backups = list((target / "backups").glob("host-config-*"))
        assert len(backups) == 1
        assert (backups[0] / "scripts/restore.sh").read_bytes() == b"previous installed wrapper\n"
        actual_runtime = {str(path.relative_to(target)) for path in target.rglob("*") if path.is_file()
            and not str(path.relative_to(target)).startswith(("backups/", "ops/", "keys/", "data/")) and path.name != ".env"}
        assert actual_runtime == set(expected)
        assert (target / "deploy/init-object-buckets.sh").is_file()
        assert (target / "frontend/nginx.conf").is_file()


@pytest.mark.parametrize("fault", ["missing", "symlink", "hardlink", "fifo"])
def test_every_dependency_checker_and_original_fixed_entry_preflight_before_effects(tmp_path, fault):
    require_linux_root()
    for fact in inventory():
        with installed_root() as source:
            path = source / fact["path"]
            raw = path.read_bytes()
            path.unlink()
            other = source / "alias-target"
            if fault in {"symlink", "hardlink"}:
                other.write_bytes(raw)
                if fault == "symlink": path.symlink_to(other)
                else: os.link(other, path)
            elif fault == "fifo":
                os.mkfifo(path)
            target = tmp_path / "untouched"
            target.mkdir(exist_ok=True)
            (target / "sentinel").write_bytes(b"no changes")
            before = snapshot(target)
            result = install(source, target)
            assert result.returncode != 0, (fact["path"], fault)
            assert snapshot(target) == before
            assert not (target / "backups").exists()


def test_changed_guarded_source_or_broken_checker_refuses_before_backup_creation(tmp_path):
    require_linux_root()
    guarded = [fact for fact in inventory() if fact["path"].startswith("backend/") or fact["path"] == "scripts/restore-host.py"]
    for relative in [fact["path"] for fact in guarded] + ["scripts/check-restore-host-bundle.py"]:
        with installed_root() as source:
            path = source / relative
            path.write_bytes(b"invalid syntax @@@\n")
            target = tmp_path / "target"
            target.mkdir(exist_ok=True)
            result = install(source, target)
            assert result.returncode != 0, relative
            assert not list(target.iterdir())


@pytest.mark.parametrize("mutation", ["duplicate", "traversal", "unknown", "nonliteral", "missing", "digest"])
def test_guard_contract_is_data_and_cannot_expand_copy_set(tmp_path, mutation):
    require_linux_root()
    with installed_root() as source:
        wrapper = source / "scripts/restore.sh"
        raw = wrapper.read_text()
        line = next(line for line in raw.splitlines() if '"backend/apps/__init__.py":' in line)
        replacement = {"duplicate": line + "\n" + line,
            "traversal": line.replace("backend/apps/__init__.py", "../escape.py"),
            "unknown": line.replace("backend/apps/__init__.py", "unreviewed.py"),
            "nonliteral": line.replace('"backend/apps/__init__.py"', '("backend/" + "apps/__init__.py")'),
            "missing": "", "digest": line.replace('"01ba', '"NOTHEX01ba')}[mutation]
        wrapper.write_text(raw.replace(line, replacement, 1))
        target = tmp_path / "target"
        target.mkdir()
        result = install(source, target)
        assert result.returncode != 0
        assert not list(target.iterdir())


def test_actual_nonroot_bundle_install_retains_caller_ownership_without_conversion():
    require_linux_root()
    import tempfile
    with installed_root() as source, tempfile.TemporaryDirectory(prefix="recovery-nonroot-install-", dir="/tmp") as directory:
        target = Path(directory)
        target.chmod(0o755)
        os.chown(target, 65534, 65534)
        env = target / ".env"
        env.write_bytes(b"PRIVATE_SENTINEL=retained\n")
        env.chmod(0o600)
        os.chown(env, 65534, 65534)
        result = install(source, target, nonroot=True)
        assert result.returncode == 0, result.stderr
        assert env.read_bytes() == b"PRIVATE_SENTINEL=retained\n" and env.stat().st_uid == 65534
        for fact in inventory():
            path = target / fact["path"]
            assert path.stat().st_uid == 65534
            assert path.stat().st_mode & 0o777 == int(fact["installed_mode"], 8)
        from tests.backup.recovery_bundle_support import run_wrapper
        result = run_wrapper(target, "--help")  # Even UID0 cannot bless operator-owned ancestry.
        assert result.returncode != 0 and "root-owned protected Linux host bundle" in result.stderr
