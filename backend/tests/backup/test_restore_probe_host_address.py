"""Real PG16 TCP probe proof; Docker/SQL admission controls are synthetic only."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timezone
import json
from urllib.parse import quote, urlencode, urlunsplit

import psycopg2
import pytest
from django.db import connection, transaction

from apps.backup.database_identity import query_live_database_identity
from apps.backup.full_restore_identity import capture_target_identity
from apps.backup.host_marker import MarkerState, marker_payload, write_marker_fsynced
from apps.backup.host_restore_admission import target_identity
from apps.backup.host_restore_transport import RestoreHostError
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.backup.models_restore import DeploymentRecoveryState
from scripts import restore_database_probe
from tests.backup.recovery_test_support import marker_rig
from tests.backup.recovery_transport_support import SyntheticTransport


@pytest.fixture
def pytest_tcp_url(transactional_db):
    """Use only the active pytest connection, never the deployment DATABASE_URL."""
    connection.ensure_connection()
    assert connection.vendor == "postgresql"
    assert connection.get_autocommit() and not connection.in_atomic_block
    name = str(connection.settings_dict["NAME"])
    # Fail closed for a non-test name, including a misconfigured reused database.
    assert name.startswith("test_"), "This lane requires an isolated test_* database."
    configured = connection.get_connection_params()
    effective = connection.connection.get_dsn_parameters()
    assert configured["dbname"] == effective["dbname"] == name
    host = effective.get("host", "")
    assert host and not host.startswith(("/", "@")) and "," not in host, (
        "This regression requires one actual TCP host; no Unix-socket fallback."
    )
    port = int(effective["port"])
    user = quote(effective["user"], safe="")
    password = configured.get("password", "")
    credentials = user + (":" + quote(str(password), safe="") if password else "")
    authority = "[" + host + "]" if ":" in host else host
    options = {key: value for key, value in effective.items()
               if key not in {"host", "port", "dbname", "user", "password"}}
    url = urlunsplit(("postgresql", credentials + "@" + authority + ":" + str(port),
                     "/" + quote(name, safe=""), urlencode(options), ""))
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        assert 160000 <= int(cursor.fetchone()[0]) < 170000
        cursor.execute("SELECT current_database(), host(inet_server_addr())")
        actual_name, address = cursor.fetchone()
        assert actual_name == name and address and "/" not in address
    return url


@pytest.mark.django_db(transaction=True)
def test_real_tcp_probe_preserves_host_port_tls_live_identity_and_target_row(pytest_tcp_url):
    # These are the legitimate singleton initializers; the transaction commits
    # before the production probe opens its separate psycopg2 connection.
    with transaction.atomic():
        row = DeploymentDatabaseIdentity.load()
        recovery = DeploymentRecoveryState.load()
        assert recovery.mode == "normal" and recovery.active_restore_id is None
    assert connection.get_autocommit() and not connection.in_atomic_block
    expected_row = {
        "id": row.pk, "database_uuid": str(row.database_uuid),
        "run_id": str(row.run_id) if row.run_id else None,
        "artifact_sha256": row.artifact_sha256,
        "capture_id": str(row.capture_id) if row.capture_id else None,
        "created_at": row.created_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
    }
    # No production query/function is mocked in this real-server regression.
    with psycopg2.connect(pytest_tcp_url) as independent:
        independent.autocommit = True
        with independent.cursor() as cursor:
            cursor.execute(
                "SELECT host(inet_server_addr()), inet_server_port(), "
                "COALESCE((SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()), false)"
            )
            address, port, tls = cursor.fetchone()
        assert address and "/" not in address and port > 0 and type(tls) is bool
        before_live = asdict(query_live_database_identity(independent))
        before_target = capture_target_identity(independent)
        assert before_target["row"] == expected_row
        assert before_live["endpoint"]["database"] == connection.settings_dict["NAME"]

        result = restore_database_probe.probe(pytest_tcp_url)

        assert result["physical"] == {"address": address, "port": port, "tls": tls}
        assert result["physical"]["address"] and "/" not in result["physical"]["address"]
        assert result["identity"] == before_live
        assert result["target_record"] == before_target
        assert result["recovery_state"] == {"mode": "normal", "active_restore": None}
        assert asdict(query_live_database_identity(independent)) == before_live
        assert capture_target_identity(independent) == before_target
    row.refresh_from_db()
    recovery.refresh_from_db()
    assert str(row.database_uuid) == expected_row["database_uuid"]
    assert recovery.mode == "normal" and recovery.active_restore_id is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("cidr,expected", [
    pytest.param("192.0.2.7/24", "192.0.2.7", id="ipv4-cidr"),
    pytest.param("2001:0DB8:0000:0000:0000:0000:0000:0007/64", "2001:db8::7", id="ipv6-cidr"),
])
def test_real_postgres_host_formats_inet_without_mask(pytest_tcp_url, cidr, expected):
    # SQL type-formatting controls only; this makes no external IPv6 network claim.
    with psycopg2.connect(pytest_tcp_url) as database:
        with database.cursor() as cursor:
            cursor.execute("SELECT host(%s::inet), (%s::inet)::text", (cidr, cidr))
            host, inet_text = cursor.fetchone()
    assert host == expected and "/" not in host
    assert "/" in inet_text and inet_text != host


def test_synthetic_exact_container_host_and_bound_identity_are_admitted(tmp_path):
    with marker_rig(tmp_path) as rig:
        transport = SyntheticTransport(rig, tmp_path)
        marker_before = rig.marker.read_bytes()
        assert target_identity(transport) == rig.identity
        assert rig.marker.read_bytes() == marker_before
        assert transport.running == {"backend", "worker", "beat", "db", "redis"}
        assert ("docker", ("inspect", "db")) in transport.events


@pytest.mark.parametrize("fault,message", [
    pytest.param("wrong-address", "not the admitted bundled SQL container", id="wrong-address"),
    pytest.param("empty-address", "not the admitted bundled SQL container", id="empty-address"),
    pytest.param("cidr-address", "not the admitted bundled SQL container", id="no-cidr-normalization"),
    pytest.param("wrong-port", "not the admitted bundled SQL container", id="wrong-port"),
    pytest.param("db-uuid", "SQL transport and application identity disagree", id="db-corroboration-drift"),
    pytest.param("marker-uuid", "disagrees with the bound host marker", id="bound-marker-drift"),
])
def test_synthetic_target_identity_rejects_exact_physical_or_identity_drift(tmp_path, fault, message):
    """Mutate synthetic wire facts or a genuine fixture marker, never DB guards."""
    with marker_rig(tmp_path) as rig:
        transport = SyntheticTransport(rig, tmp_path)
        # Establish that this same fixture passes every existing root/marker check.
        assert target_identity(transport) == rig.identity
        probe = deepcopy(transport.probe())
        physical_faults = {
            "wrong-address": ("address", "172.19.0.3"),
            "empty-address": ("address", ""),
            "cidr-address": ("address", "172.19.0.2/32"),
            "wrong-port": ("port", 5433),
        }
        if fault in physical_faults:
            key, value = physical_faults[fault]
            probe["physical"][key] = value
        transport.probe = lambda: deepcopy(probe)
        actual_sql = transport.sql
        sql_calls = []

        def synthetic_sql(command):
            sql_calls.append(command)
            response = json.loads(actual_sql(command))
            if fault == "db-uuid":
                response["uuid"] = "770a9c81-1234-4aaa-8c81-0123456789ab"
            return json.dumps(response)

        transport.sql = synthetic_sql
        if fault == "marker-uuid":
            server = deepcopy(rig.identity.server_identity)
            server["database_uuid"] = "770a9c81-1234-4aaa-8c81-0123456789ab"
            drifted = replace(rig.identity, server_identity=server)
            write_marker_fsynced(rig.marker, marker_payload(MarkerState.NORMAL, drifted))
        marker_before = rig.marker.read_bytes()
        with pytest.raises(RestoreHostError, match=message):
            target_identity(transport)
        assert len(sql_calls) == (0 if fault in physical_faults else 1)
        assert rig.marker.read_bytes() == marker_before
        assert transport.running == {"backend", "worker", "beat", "db", "redis"}
