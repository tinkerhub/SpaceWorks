"""Six Linux UID0 compatibility cases: real controller/crypto/root marker/flock.

Docker, age, SQL, build/storage probes and DB registration are synthetic. These
are control-flow tests, never installed-host, SQL restore or attestation claims.
"""

import json

import pytest

from apps.backup.host_marker import MarkerState, read_marker
from apps.backup.host_restore_transport import RestoreHostError
from apps.backup.import_preflight import ImportPreflightError
from tests.backup.full_backup_fixture_helpers import make_full_fixture
from tests.backup.full_backup_host_helpers import RESTORE_ID, host_case, run_controller


def index(rows, name):
    return next(i for i, row in enumerate(rows) if row["name"] == name)


def test_import_refusal_precedes_env_services_intent_and_grants(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    fixture.manifest["archive_signature"]["value"] = "AA=="
    fixture.write()
    with host_case(tmp_path, monkeypatch, fixture) as (rig, t):
        before, marker = t.static_env.read_bytes(), rig.marker.read_bytes()
        with pytest.raises(ImportPreflightError, match="manifest_signature"):
            run_controller(monkeypatch, t, "import", fixture.encrypted, "superadmin",
                           fixture.kwargs()["expected_sha256"])
        assert [row["name"] for row in t.trace if row["name"] != "synthetic-sql"] == [
            "synthetic-age", "preflight_backup_import"]
        preflight = next(row["args"] for row in t.trace if row["name"] == "preflight_backup_import")
        assert preflight[:10] == ("run", "--rm", "--no-deps", "-T", "backend", "--role",
                                  "management", "python", "manage.py", "preflight_backup_import")
        assert "--restore-id" not in preflight
        assert t.static_env.read_bytes() == before and rig.marker.read_bytes() == marker
        assert t.running == {"backend", "worker", "beat", "db", "redis"}
        assert not list(t.ops.glob("private/*/bundle"))  # Only bounded metadata projected.
        assert not list(t.ops.glob("private/*/configuration.json"))
        assert not list(rig.ledger.path.parent.glob("*.jsonl"))
        assert not list(t.root.glob(".env.pre-restore-*"))
        assert not any(isinstance(event, str) and (event in {"grants", "dump", "sql-restore"} or
                       event.startswith(("stop:", "start:", "control:"))) for event in t.events)


def test_import_success_checks_prospective_before_env_then_installed_before_supervisor(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    with host_case(tmp_path, monkeypatch, fixture) as (rig, t):
        before = t.static_env.read_bytes()
        # Stop at the first SQL-stage management call, after real blocked config
        # installation and strict installed-key validation, before replacement SQL.
        t.failure = "control:stage"
        with pytest.raises(RestoreHostError, match="synthetic transport failure"):
            run_controller(monkeypatch, t, "import", fixture.encrypted, "superadmin",
                           fixture.kwargs()["expected_sha256"])
        rows = t.trace
        static, registered, described = [index(rows, name) for name in (
            "preflight_backup_import", "import_backup_archive", "control:describe")]
        preflights = [i for i, row in enumerate(rows) if row["name"] == "control:preflight"]
        assert len(preflights) == 3
        assert static < registered < described < preflights[0] < index(rows, "control:claim")
        assert index(rows, "control:claim") < preflights[1] < index(rows, "control:quiesce") < preflights[2]
        stopped = next(i for i, row in enumerate(rows) if row["name"] == "compose:stop"
                       and row["args"] == ("stop", "backend", "worker", "beat"))
        assert rows[stopped]["environment"] == before
        assert rows[stopped]["marker"] == MarkerState.RESTORE_BLOCKED
        assert index(rows, "control:quiesce") < stopped < preflights[2]
        assert all(row["environment"] == before for row in rows[:stopped + 1])
        assert all(row["environment"] == before and row["marker"] == MarkerState.NORMAL
                   for row in rows[:registered + 1])
        registered_args = rows[registered]["args"]
        assert "--restore-id" not in registered_args and "--prospective-record" in registered_args
        assert all("--prospective-record" in rows[i]["args"] for i in preflights[:2])
        installed = rows[preflights[2]]
        assert "--prospective-record" not in installed["args"]
        assert installed["marker"] == MarkerState.RESTORE_BLOCKED
        assert not installed["running"] & {"backend", "worker", "beat"}
        assert all(row["marker"] == MarkerState.RESTORE_BLOCKED and
                   not row["running"] & {"backend", "worker", "beat"}
                   for row in rows if row["environment"] != before)
        assert installed["environment"] == t.static_env.read_bytes() != before
        assert "TARGET_ONLY=keep\n" in t.static_env.read_text()
        for role in ("backend", "worker", "beat"):
            assert all(t.config["services"][role]["environment"][key] == value
                       for key, value in fixture.secrets.items())
        private = next(t.ops.glob("private/inplace-*/configuration.json")).parent
        assert (private / "environment-before.env").read_bytes() == before
        assert (private / "environment.old").read_bytes() == before
        assert (private / "environment.new").read_bytes() == t.static_env.read_bytes()
        assert (private / "bundle/database.dump").read_bytes() == fixture.members["database.dump"]
        assert json.loads((private / "input.json").read_bytes())["restore_id"] == RESTORE_ID
        assert read_marker(rig.marker).state == MarkerState.RESTORE_BLOCKED
        assert "preview-sql" in t.events and "sql-restore" not in t.events
        assert not any(row["args"][0].startswith("pg_restore") and "--clean" in row["args"][0]
                       for row in rows if row["name"] == "synthetic-sql")
        assert "control:rehydrate" not in t.events


def test_full_supervisor_bootstraps_identity_before_any_postreplacement_management(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    with host_case(tmp_path, monkeypatch, fixture) as (rig, t):
        run_controller(monkeypatch, t, "restore", RESTORE_ID)
        rows = t.trace
        preflights = [i for i, row in enumerate(rows) if row["name"] == "control:preflight"]
        assert len(preflights) == 4
        assert preflights[0] < index(rows, "control:claim") < preflights[1] < index(rows, "control:quiesce")
        replaced = next(i for i, row in enumerate(rows) if row["name"] == "synthetic-sql"
                        and row["args"][0].startswith("pg_restore") and "--clean" in row["args"][0])
        bootstrap = next(i for i, row in enumerate(rows) if row["name"] == "synthetic-grants"
                         and "SPACEWORKS_RESTORE_IDENTITY=1" in row["args"])
        rehydrate = index(rows, "control:rehydrate")
        assert preflights[2] < replaced < bootstrap < rehydrate < index(rows, "control:validate") < preflights[3]
        assert not any(row["name"].startswith("control:") for row in rows[replaced + 1:bootstrap])
        assert rows[bootstrap]["args"] == ("run", "--rm", "--no-deps", "-T", "-e",
            "SPACEWORKS_GRANTS_ONLY=1", "-e", "SPACEWORKS_RESTORE_IDENTITY=1", "orchestration-ready")
        identity = json.loads(rows[bootstrap]["identity"])
        assert set(identity) == {"full_target_identity", "restore_operation"}
        assert identity["full_target_identity"] == t.probe()["target_record"]
        assert identity["restore_operation"]["restore_id"] == RESTORE_ID
        assert identity["restore_operation"]["artifact_sha256"] == fixture.kwargs()["expected_sha256"]
        assert identity["restore_operation"]["capture_id"] == fixture.manifest["capture_id"]
        assert all(row["marker"] == MarkerState.RESTORE_BLOCKED for row in rows[replaced:rehydrate + 1])
        assert read_marker(rig.marker).state == MarkerState.QUARANTINED_AFTER_CUTOVER
        assert t.running & {"backend", "worker", "beat"} == {"backend"}
        assert "start:worker,beat" not in t.events


@pytest.mark.parametrize("token", ["preflight-ok", "unknown", "compound-coordinator-ready"])
def test_changed_or_unsupported_supervisor_token_refuses_before_destructive_work(tmp_path, monkeypatch, token):
    fixture = make_full_fixture(tmp_path)
    with host_case(tmp_path, monkeypatch, fixture) as (rig, t):
        before, marker = t.static_env.read_bytes(), rig.marker.read_bytes()
        t.second_token = token
        with pytest.raises(RestoreHostError, match="authenticated restore path changed"):
            run_controller(monkeypatch, t, "restore", RESTORE_ID)
        assert t.preflights == 2  # Exact FULL token accepted once, then changed after claim.
        assert "control:claim" in t.events
        assert "control:quiesce" not in t.events
        assert not any(isinstance(event, str) and (event in {"dump", "sql-restore", "grants", "createdb", "dropdb"} or
                       event.startswith(("stop:", "start:"))) for event in t.events)
        assert not any(row["name"] == "synthetic-sql" and
                       ("pg_restore" in row["args"][0] or "pg_terminate_backend" in row["args"][0]) for row in t.trace)
        assert t.static_env.read_bytes() == before and rig.marker.read_bytes() == marker
        assert t.running == {"backend", "worker", "beat", "db", "redis"}
        assert not list(t.ops.glob("private/*/configuration.json"))
        assert not list(rig.ledger.path.parent.glob("*.jsonl"))
