"""Bare installer fingerprints helper/data bytes without importing migration code."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from apps.backup import producer_capability
from tests.backup.migration_fingerprint_test_support import (
    DATA, ORPHAN, TRIGGER, install_tree,
)


CODE = r"""
import re
import runpy
import sys

installer, marker, scripts, entrypoint, migrations = sys.argv[1:]
loaded = runpy.run_path(installer, run_name="probe")
key = loaded["verification_public_key"](sys.stdin.read())
loaded["install_capability"](
    marker=marker, scripts_dir=scripts, entrypoint=entrypoint,
    migrations_dir=migrations, verification_key=key, require_root_owned=False,
)
from django.conf import settings
assert settings.configured is False
assert not any(re.match(r"^apps\.[^.]+\.models(?:\.|$)", name) for name in sys.modules)
assert "django.apps.registry" not in sys.modules
assert "apps.backup.migration_fingerprint" in sys.modules
"""


def test_standalone_installer_tracks_helper_and_data_drift(
    installed_producer_capability, settings, tmp_path
):
    installation = installed_producer_capability
    root = install_tree(installation, settings)
    installer = Path(__file__).resolve().parents[2] / "scripts/install_producer_capability.py"
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)

    def install_without_settings():
        result = subprocess.run(
            [sys.executable, "-I", "-c", CODE, str(installer),
             str(installation["marker"].resolve()), str(installation["scripts"].resolve()),
             str(installation["entrypoint"].resolve()), str(root)],
            env=env, cwd=tmp_path.resolve(),
            input=f"BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY={settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY}\n",
            text=True, capture_output=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        marker_bytes = installation["marker"].read_bytes()
        assert settings.BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY.encode() not in marker_bytes
        return json.loads(marker_bytes)

    payload = install_without_settings()
    producer_capability.assert_producer_capability()
    for relative in (TRIGGER, DATA, ORPHAN):
        marker_before = installation["marker"].read_bytes()
        path = root / relative
        path.write_bytes(path.read_bytes() + b"\n# changed helper/data\n")
        with pytest.raises(producer_capability.ProducerCapabilityRefused) as refused:
            producer_capability.assert_producer_capability()
        assert refused.value.reason == "producer-capability-migration-version"
        assert installation["marker"].read_bytes() == marker_before

        regenerated = install_without_settings()
        assert regenerated["migration_version"] != payload["migration_version"]
        assert producer_capability.assert_producer_capability().migration_version == regenerated["migration_version"]
        payload = regenerated
