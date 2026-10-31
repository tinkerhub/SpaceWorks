"""Exact shell forwarding plus actual signed-full controller admission refusal."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from apps.backup.import_preflight import ImportPreflightError
from tests.backup.full_backup_fixture_helpers import make_full_fixture
from tests.backup.full_backup_host_helpers import host_case, run_controller


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IMPORT_SCRIPT = REPOSITORY_ROOT / "scripts/import-backup.sh"


@pytest.mark.parametrize("extra", [[], ["a" * 64]])
def test_wrapper_forwards_exact_import_arguments_to_executable_restore(tmp_path, extra):
    scripts = tmp_path / "deployment/scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / "import-backup.sh"
    wrapper.write_bytes(IMPORT_SCRIPT.read_bytes())
    wrapper.chmod(0o755)
    log = tmp_path / "forwarded.json"
    stub = scripts / "restore.sh"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['FORWARD_LOG']).write_text(json.dumps(sys.argv[1:]))\n"
        "raise SystemExit(23)\n"
    )
    stub.chmod(0o755)
    arguments = [str(tmp_path / "archive with spaces.tar.age"), "target admin", *extra]
    completed = subprocess.run(
        [str(wrapper), *arguments], env={**os.environ, "FORWARD_LOG": str(log)},
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 23
    assert json.loads(log.read_text()) == ["--import", *arguments]


def test_failing_preflight_precedes_environment_and_service_mutation(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    fixture.manifest["archive_signature"]["value"] = "AA=="
    fixture.write()
    with host_case(tmp_path, monkeypatch, fixture) as (rig, transport):
        original_env = transport.static_env.read_bytes()
        original_marker = rig.marker.read_bytes()
        environment = dict(os.environ)
        with pytest.raises(ImportPreflightError) as refused:
            run_controller(monkeypatch, transport, "import", fixture.encrypted,
                           "target-admin", fixture.kwargs()["expected_sha256"])
        assert refused.value.reason == "manifest_signature"
        assert transport.static_env.read_bytes() == original_env
        assert rig.marker.read_bytes() == original_marker
        assert dict(os.environ) == environment
        assert not list(transport.root.glob(".env.pre-restore-*"))
        assert transport.running == {"backend", "worker", "beat", "db", "redis"}
        invocations = [row for row in transport.trace if row["name"] != "synthetic-sql"]
        assert [row["name"] for row in invocations] == ["synthetic-age", "preflight_backup_import"]
        preflight = invocations[-1]["args"]
        assert preflight[:10] == ("run", "--rm", "--no-deps", "-T", "backend", "--role",
                                  "management", "python", "manage.py", "preflight_backup_import")
        assert "--force-recreate" not in preflight
        assert "import_backup_archive" not in [row["name"] for row in transport.trace]
        assert not list(transport.ops.glob("import-*"))
        assert not list(transport.ops.glob("private/*/bundle"))
        assert not list(transport.ops.glob("private/*/configuration.json"))
        assert not list(rig.ledger.path.parent.glob("*.jsonl"))
        assert not any(isinstance(event, str) and (event in {"grants", "dump", "sql-restore", "createdb", "dropdb"}
                       or event.startswith(("stop:", "start:", "control:"))) for event in transport.events)
        assert not any(row["name"] == "synthetic-sql" and any(command in row["args"][0]
                       for command in ("pg_restore", "pg_terminate_backend")) for row in transport.trace)
