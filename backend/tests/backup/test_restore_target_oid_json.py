"""Real PG16 target SQL/probe; Docker inspection and transport are synthetic.

Requires isolated test_* TCP PostgreSQL and actual Linux UID0. This does not
attest Docker, an installed source/image pair, or a completed restore.
"""

from contextlib import closing, contextmanager, redirect_stdout
from copy import deepcopy
from datetime import timezone
from io import StringIO
import json
import secrets
import shlex
import sys
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn
import pytest
from django.db import connection, transaction

from apps.backup.host_marker import (
    DatabaseIdentity, MarkerState, marker_payload, read_marker, write_marker_fsynced,
)
from apps.backup.host_restore_admission import target_identity
from apps.backup.host_restore_transport import RestoreHostError
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.backup.models_restore import DeploymentRecoveryState
from scripts import restore_database_probe
from tests.backup.recovery_test_support import require_linux_root
from tests.backup.test_restore_probe_host_address import pytest_tcp_url  # noqa: F401


TABLES = ("backup_deploymentdatabaseidentity", "backup_deploymentrecoverystate")


@contextmanager
def restricted_login(owner, owner_url):
    """Grant only this newly created login's two operational-table reads."""
    role = "oid_json_" + uuid.uuid4().hex
    password = secrets.token_hex(32)
    identifier = sql.Identifier(role)
    tables = sql.SQL(", ").join(sql.Identifier("public", name) for name in TABLES)
    with owner.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        database = sql.Identifier(cursor.fetchone()[0])
        cursor.execute(sql.SQL(
            "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(identifier, sql.Literal(password)))
    try:
        with owner.cursor() as cursor:
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, identifier))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(identifier))
            cursor.execute(sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(tables, identifier))
        parameters = parse_dsn(owner_url)
        parameters.update(user=role, password=password)
        app_url = make_dsn(**parameters)
        with closing(psycopg2.connect(app_url)) as application:
            application.autocommit = True
            with application.cursor() as cursor:
                cursor.execute(
                    "SELECT current_user, session_user, rolsuper, rolcreatedb, "
                    "rolcreaterole, rolreplication, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
                actual_user, session_user, *capabilities = cursor.fetchone()
                assert actual_user == session_user == role
                assert capabilities == [False] * 5
                cursor.execute(
                    "SELECT count(*) FROM pg_auth_members "
                    "WHERE member = (SELECT oid FROM pg_roles WHERE rolname = current_user)"
                )
                assert cursor.fetchone()[0] == 0
                cursor.execute(
                    "SELECT table_schema, table_name, privilege_type "
                    "FROM information_schema.role_table_grants WHERE grantee = current_user"
                )
                assert set(cursor.fetchall()) == {("public", name, "SELECT") for name in TABLES}
        yield app_url
    finally:
        # No DROP OWNED, global PUBLIC function ACL edits, or unrelated cleanup.
        with owner.cursor() as cursor:
            cursor.execute(sql.SQL("REVOKE SELECT ON TABLE {} FROM {}").format(tables, identifier))
            cursor.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(identifier))
            cursor.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(database, identifier))
            cursor.execute(sql.SQL("DROP ROLE {}").format(identifier))


class PostgresTargetTransport:
    """Synthetic Compose/inspect boundary around real production functions/SQL."""

    def __init__(self, host, owner, owner_url, app_url, monkeypatch, physical, fault):
        self.host, self.owner = host, owner
        self.owner_url, self.app_url, self.monkeypatch = owner_url, app_url, monkeypatch
        self.physical, self.fault = physical, fault
        self.events, self.raw_sql_json, self.returned_sql_json = [], None, None
        self.probe_json = None

    def compose(self, *args, json_result=False):
        self.events.append(("compose", args))
        if args == ("ps", "-q", "db"):
            assert json_result is False
            return "synthetic-db-container"
        assert args == (
            "run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
            "orchestration-ready", "/app/scripts/restore_database_probe.py",
        )
        assert json_result is True
        # Only process inputs/stdout are redirected. UID, connections, probe(),
        # main(), identity/row/system checks and target_identity() stay real.
        output = StringIO()
        with self.monkeypatch.context() as process, redirect_stdout(output):
            process.setenv("DATABASE_URL", self.owner_url)
            process.setenv("SPACEWORKS_RUNTIME_DATABASE_URL", self.app_url)
            process.setattr(sys, "argv", ["restore_database_probe.py"])
            restore_database_probe.main()
        self.probe_json = json.loads(output.getvalue())
        return self.probe_json

    def docker(self, *args, json_result=False):
        self.events.append(("docker", args))
        assert args == ("inspect", "synthetic-db-container") and json_result is True
        # This is explicitly synthetic inspection, using an independent actual
        # PostgreSQL address, never a fabricated application physical endpoint.
        return [{"NetworkSettings": {"Networks": {
            "synthetic": {"IPAddress": self.physical["address"]},
        }}}]

    def sql(self, command):
        self.events.append(("sql",))
        argv = shlex.split(command)
        assert len(argv) == 11
        assert argv[:-1] == [
            "psql", "-X", "-v", "ON_ERROR_STOP=1", "-At", "-U",
            "$POSTGRES_USER", "-d", "$POSTGRES_DB", "-c",
        ]
        statement = argv[-1]
        assert statement.startswith("SELECT json_build_object(") and ";" not in statement
        # Execute the exact emitted -c SELECT, not a copied OID expression.
        with self.owner.cursor() as cursor:
            cursor.execute(statement)
            value = cursor.fetchone()[0]
            assert cursor.fetchone() is None
        assert type(value) is dict
        self.raw_sql_json = deepcopy(value)
        if self.fault == "system":
            assert type(value["system"]) is str and value["system"]
            value["system"] = "1" if value["system"] != "1" else "2"
        elif self.fault == "oid":
            assert type(value["oid"]) is int
            value["oid"] = value["oid"] % ((1 << 32) - 1) + 1
        self.returned_sql_json = deepcopy(value)
        # Native PG JSON types survive this encoding: no str/int coercion.
        return json.dumps(value)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fault", [
    pytest.param(None, id="native-oid-number-admitted"),
    pytest.param("system", id="different-nonnull-system-refused"),
    pytest.param("oid", id="different-numeric-oid-refused"),
])
def test_real_pg16_target_oid_json(pytest_tcp_url, tmp_path, monkeypatch, fault):
    require_linux_root()
    # Legitimate initializers commit before any separate owner/app connection.
    with transaction.atomic():
        identity_row = DeploymentDatabaseIdentity.load()
        recovery = DeploymentRecoveryState.load()
        assert recovery.mode == "normal" and recovery.active_restore_id is None
    assert connection.get_autocommit() and not connection.in_atomic_block
    expected_row = {
        "id": identity_row.pk, "database_uuid": str(identity_row.database_uuid),
        "run_id": str(identity_row.run_id) if identity_row.run_id else None,
        "artifact_sha256": identity_row.artifact_sha256,
        "capture_id": str(identity_row.capture_id) if identity_row.capture_id else None,
        "created_at": identity_row.created_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
    }
    with closing(psycopg2.connect(pytest_tcp_url)) as owner:
        owner.autocommit = True
        with owner.cursor() as cursor:
            cursor.execute(
                "SELECT host(inet_server_addr()), inet_server_port(), "
                "COALESCE((SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()), false)"
            )
            address, port, tls = cursor.fetchone()
        assert address and "/" not in address and port == 5432 and type(tls) is bool
        physical = {"address": address, "port": port, "tls": tls}
        with restricted_login(owner, pytest_tcp_url) as app_url:
            before_owner = restore_database_probe.probe(pytest_tcp_url)
            before_app = restore_database_probe.probe(app_url)
            assert before_owner["physical"] == before_app["physical"] == physical
            assert before_owner["target_record"]["row"] == before_app["target_record"]["row"] == expected_row
            live = before_owner["identity"]
            assert type(live["oid"]) is int
            assert type(live["system_identifier"]) is str and live["system_identifier"]
            expected = DatabaseIdentity(live["endpoint"]["database"], live["oid"], {
                key: live[key] for key in ("endpoint", "database_uuid", "system_identifier")
            })
            host = tmp_path / "host"
            marker = host / "public/restore-marker.json"
            write_marker_fsynced(marker, marker_payload(MarkerState.NORMAL, expected))
            assert read_marker(marker).require_bound_database() == expected
            marker_before = marker.read_bytes()
            transport = PostgresTargetTransport(
                host, owner, pytest_tcp_url, app_url, monkeypatch, physical, fault,
            )
            if fault is None:
                assert target_identity(transport) == expected
            else:
                with pytest.raises(RestoreHostError, match="^Bundled SQL transport and application identity disagree\\.$"):
                    target_identity(transport)
            # main() really ran both roles and retained the owner's nonnull
            # system corroboration; each role's original facts remain unchanged.
            assert transport.probe_json == before_owner
            assert restore_database_probe.probe(pytest_tcp_url) == before_owner
            assert restore_database_probe.probe(app_url) == before_app
            raw = transport.raw_sql_json
            assert raw == {"name": expected.name, "oid": expected.oid,
                           "uuid": live["database_uuid"], "system": live["system_identifier"]}
            assert type(raw["oid"]) is int  # PG raw oid used to encode as str.
            changed = {key for key in raw if raw[key] != transport.returned_sql_json[key]}
            assert changed == (set() if fault is None else {fault})
            if fault:
                assert type(transport.returned_sql_json[fault]) is type(raw[fault])
            assert transport.events == [
                ("compose", ("run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
                             "orchestration-ready", "/app/scripts/restore_database_probe.py")),
                ("compose", ("ps", "-q", "db")),
                ("docker", ("inspect", "synthetic-db-container")), ("sql",),
            ]
            assert marker.read_bytes() == marker_before
    identity_row.refresh_from_db()
    recovery.refresh_from_db()
    assert str(identity_row.database_uuid) == expected_row["database_uuid"]
    assert recovery.mode == "normal" and recovery.active_restore_id is None
