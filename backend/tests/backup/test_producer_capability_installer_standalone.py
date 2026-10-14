import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from apps.backup.producer_capability import PRIVILEGED_SCRIPT_NAMES


CODE = r"""
import re
import runpy
import sys

installer, marker, scripts_dir, entrypoint, migrations_dir = sys.argv[1:]
loaded = runpy.run_path(installer, run_name="probe")
key = loaded["verification_public_key"](sys.stdin.read())
loaded["install_capability"](
    marker=marker,
    scripts_dir=scripts_dir,
    entrypoint=entrypoint,
    migrations_dir=migrations_dir,
    verification_key=key,
    require_root_owned=False,
)

from django.conf import settings

assert settings.configured is False
assert not any(re.match(r"^apps\.[^.]+\.models$", name) for name in sys.modules)
"""


def test_installer_runs_without_django_settings_or_app_loading(
    tmp_path, settings
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for index, name in enumerate(PRIVILEGED_SCRIPT_NAMES):
        (scripts / name).write_bytes(f"script-{index}:{name}\n".encode("ascii"))
    entrypoint = tmp_path / "entrypoint.py"
    entrypoint.write_bytes(b"entrypoint bytes independently hashed\n")
    migration = tmp_path / "apps" / "backup" / "migrations"
    migration.mkdir(parents=True)
    (migration / "0001_initial.py").write_bytes(b"migration bytes\n")
    marker = tmp_path / "host" / "public" / "producer-capability.json"
    installer = (
        Path(__file__).resolve().parents[2]
        / "scripts" / "install_producer_capability.py"
    )
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)

    result = subprocess.run(
        [
            sys.executable, "-c", CODE, str(installer), str(marker),
            str(scripts), str(entrypoint), str(tmp_path / "apps"),
        ],
        env=env,
        cwd=tmp_path,
        input=f"BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY={settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY}\n",
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    recorded = json.loads(marker.read_text(encoding="utf-8"))
    independently_hashed = {
        name: hashlib.sha256((scripts / name).read_bytes()).hexdigest()
        for name in PRIVILEGED_SCRIPT_NAMES
    }
    assert recorded["privileged_scripts"] == independently_hashed
