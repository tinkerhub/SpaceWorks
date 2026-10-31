"""Real fresh-install packaging; all release/Docker/setup calls synthetic."""

import hashlib
import os
from pathlib import Path
import tempfile

import pytest

from tests.backup.recovery_bundle_support import installed_root, inventory, run_wrapper
from tests.backup.recovery_fresh_install_support import fresh_install


@pytest.mark.parametrize("nonroot", [False, True])
def test_actual_fresh_root_or_nobody_install_preserves_explicit_ownership_mode(nonroot):
    with installed_root() as source, tempfile.TemporaryDirectory(prefix="recovery-fresh-", dir="/tmp") as value:
        workspace = Path(value)
        workspace.chmod(0o755)
        if nonroot:
            os.chown(workspace, 65534, 65534)
        status, output, target = fresh_install(source, workspace, nonroot=nonroot)
        assert status == 0, output
        assert "synthetic setup transport reached" in output
        uid = 65534 if nonroot else 0
        assert target.stat().st_uid == uid
        for fact in inventory():
            path = target / fact["path"]
            assert path.stat().st_uid == uid
            assert hashlib.sha256(path.read_bytes()).hexdigest() == fact["sha256"]
        assert not (target / ".env").exists()  # Setup was only the labeled wire seam.
        if nonroot:
            result = run_wrapper(target, "--help")
            assert result.returncode != 0 and "root-owned protected Linux host bundle" in result.stderr
        else:
            result = run_wrapper(target, "--help")
            assert result.returncode == 0, result.stderr


def test_fresh_archive_preflight_refuses_missing_transitive_file_before_target_move():
    with installed_root() as source, tempfile.TemporaryDirectory(prefix="recovery-fresh-bad-", dir="/tmp") as value:
        workspace = Path(value)
        workspace.chmod(0o755)
        (source / "backend/apps/backup/inplace_marker.py").unlink()
        status, output, target = fresh_install(source, workspace)
        assert status != 0
        assert "restore host bundle is incomplete or differs" in output
        assert not target.exists()
        assert "synthetic setup transport reached" not in output
        assert not list(workspace.glob(".spaceworks-stage.*"))
