"""Load the actual fixed bootstrap file without invoking its command entrypoint."""

import importlib.util
from io import StringIO
import json
from pathlib import Path

from psycopg2 import Error
from psycopg2.extensions import make_dsn
import pytest

from apps.backup import full_restore_identity


def load_bootstrap():
    path = Path(__file__).resolve().parents[2] / "scripts/bootstrap_host_orchestration.py"
    spec = importlib.util.spec_from_file_location("stage3_full_fixed_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_bootstrap_grant_rollback(monkeypatch, database, captured, marker, runtime_role):
    """Run real bootstrap helpers, failing only after real grants have completed.

    Psycopg's connection.dsn masks the password. Build the transport from the
    existing Django test connection parameters instead; never log that string.
    Witnesses contain only helper stages and exception classes, not driver text.
    """
    __tracebackhide__ = True
    bootstrap = load_bootstrap()
    params = dict(database.get_connection_params())
    for key in ("cursor_factory", "connection_factory"):
        params.pop(key, None)  # Python driver options are not libpq DSN fields.
    try:
        maintenance_dsn = make_dsn(**params)
    except Error as exc:
        raise RuntimeError(f"bootstrap-transport: {type(exc).__name__}") from None
    assert params["dbname"] == captured["identity"]["name"]
    assert params["dbname"].startswith("spaceworks_backup_full_stage3_")
    witnesses = []
    real_identity = bootstrap.restore_target_identity
    real_provision = bootstrap.provision_runtime_role
    real_grants = bootstrap.apply_grant_state
    identity_connection = []

    def observed(label, helper, *args):
        __tracebackhide__ = True
        witnesses.append((label, "enter"))
        try:
            result = helper(*args)
        except Exception as exc:
            witnesses.append((label, type(exc).__name__))
            raise
        witnesses.append((label, "complete"))
        return result

    def identity(db, control, path):
        __tracebackhide__ = True
        assert not db.autocommit
        result = observed("identity-restore", real_identity, db, control, path)
        identity_connection.append(db)
        return result

    def provision(cursor, target, password):
        __tracebackhide__ = True
        assert cursor.connection is identity_connection[0] and not cursor.connection.autocommit
        result = observed("role-provision", real_provision, cursor, target, password)
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", [runtime_role])
        assert cursor.fetchone() == (1,)
        return result

    def grants(cursor, target, state):
        __tracebackhide__ = True
        assert cursor.connection is identity_connection[0] and not cursor.connection.autocommit
        observed("grants", real_grants, cursor, target, state)
        assert full_restore_identity._read_row(cursor.connection) == captured["row"]
        witnesses.append(("final-injection", "RuntimeError"))
        raise RuntimeError("simulated final grant failure")

    with monkeypatch.context() as patch:
        patch.setenv("SPACEWORKS_RESTORE_IDENTITY", "1")
        patch.delenv("SPACEWORKS_GRANT_DATABASE_NAME", raising=False)
        patch.setenv("SPACEWORKS_HOST_MARKER_WRITE_PATH", str(marker))
        patch.setattr(bootstrap.sys, "stdin", StringIO(json.dumps({"full_target_identity": captured})))
        patch.setattr(bootstrap, "restore_target_identity", identity)
        patch.setattr(bootstrap, "provision_runtime_role", provision)
        patch.setattr(bootstrap, "apply_grant_state", grants)
        with pytest.raises(RuntimeError, match=r"^Role/grant reprovisioning failed\.$"):
            bootstrap._grant_only(
                maintenance_dsn,
                f"postgres://{runtime_role}:fixture-password@localhost/{params['dbname']}",
            )
    assert witnesses == [
        ("identity-restore", "enter"), ("identity-restore", "complete"),
        ("role-provision", "enter"), ("role-provision", "complete"),
        ("grants", "enter"), ("grants", "complete"),
        ("final-injection", "RuntimeError"),
    ], witnesses
    return witnesses
