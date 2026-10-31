"""Real login binding and observing wrappers; no simulated SQL or dump bytes."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import secrets
import uuid

import psycopg2
from psycopg2 import sql
import pytest
from django.conf import settings
from django.db import connections, transaction

from apps.backup import archive_payload
from apps.backup.database_grants import GrantTarget, apply_grant_state, provision_runtime_role
from apps.backup.full_source_identity import capture_source_identity
from tests.backup.full_backup_privilege_helpers import hardened_control_acl


@contextmanager
def isolated_runtime_login():
    """Use the owner only to provision/clean up the normal runtime grant set."""
    __tracebackhide__ = True  # Credentials must not appear in assertion locals.
    database = connections["default"]
    assert not database.in_atomic_block
    owner = psycopg2.connect(**database.get_connection_params())
    owner.autocommit = True
    role = "full_runtime_" + uuid.uuid4().hex
    target = GrantTarget(database=database.settings_dict["NAME"], runtime_role=role)
    password = secrets.token_urlsafe(48)
    public_create = False
    try:
        # Default PG16 PUBLIC EXECUTE would make a restricted role's control
        # query succeed. Bound the database before provisioning, restore in finally.
        with hardened_control_acl(database) as acl:
            with owner.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace n, "
                    "LATERAL aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) a "
                    "WHERE n.nspname = 'public' AND a.grantee = 0 "
                    "AND a.privilege_type = 'CREATE')"
                )
                public_create = cursor.fetchone()[0]
                provision_runtime_role(cursor, target, password)
                apply_grant_state(cursor, target, "normal")
            with _bind_default_login(role, password):
                yield role
        assert acl["after"]["grants"] == acl["before"]["grants"]
    finally:
        try:
            with owner.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
                if cursor.fetchone():
                    cursor.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(sql.Identifier(role)))
                    cursor.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE usename = %s AND pid <> pg_backend_pid()", [role],
                    )
                    # Also removes this role's future-object default grants.
                    cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                    cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
                if public_create:
                    cursor.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
        finally:
            owner.close()


@contextmanager
def _bind_default_login(role, password):
    """Bind ORM connections and the separate libpq environment used by pg_dump."""
    __tracebackhide__ = True
    database = connections["default"]
    original_settings = settings.DATABASES
    original_handler = connections.databases["default"]
    original_wrapper = database.settings_dict
    config = deepcopy(original_wrapper)
    config.update(USER=role, PASSWORD=password, CONN_MAX_AGE=0)
    # A service/DSN option must not silently choose the maintenance identity.
    for key in ("user", "password", "dbname", "database", "service", "servicefile"):
        config.get("OPTIONS", {}).pop(key, None)
    connections.close_all()
    try:
        settings.DATABASES = {**original_settings, "default": config}
        connections.databases["default"] = config
        database.settings_dict = config
        yield
    finally:
        try:
            connections.close_all()
        finally:
            database.settings_dict = original_wrapper
            connections.databases["default"] = original_handler
            settings.DATABASES = original_settings


def assert_runtime_session(role):
    """Require an actual LOGIN session, all elevated flags off, no memberships."""
    __tracebackhide__ = True
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT current_user = %s, session_user = %s, rolcanlogin, "
            "rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolreplication, rolbypassrls, "
            "pg_has_role(current_user, 'pg_monitor', 'MEMBER'), "
            "EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid) "
            "FROM pg_roles r WHERE rolname = current_user", [role, role],
        )
        if cursor.fetchone() != (True, True, True, False, False, False, False, False, False, False, False):
            pytest.fail("Capture must use the fresh, unprivileged runtime LOGIN session.")


def source_facts_with_denied_control(role):
    """Exercise permission denial inside a recoverable source transaction."""
    __tracebackhide__ = True
    with transaction.atomic():
        assert_runtime_session(role)
        # Use the real driver's cursor so Django does not translate the required
        # InsufficientPrivilege into ProgrammingError before we inspect it.
        with connections["default"].connection.cursor() as cursor:
            cursor.execute("SELECT has_function_privilege(current_user, "
                           "'pg_catalog.pg_control_system()', 'EXECUTE')")
            assert cursor.fetchone() == (False,)
            cursor.execute("SAVEPOINT expected_control_denial")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute("SELECT system_identifier FROM pg_catalog.pg_control_system()")
            cursor.execute("ROLLBACK TO SAVEPOINT expected_control_denial")
            cursor.execute("RELEASE SAVEPOINT expected_control_denial")
        facts = capture_source_identity(connections["default"].connection)
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)
        assert facts[1]["system_identifier"] is None
        return facts


@contextmanager
def observe_real_dump(monkeypatch, role):
    """Inspect the real child command immediately before delegating unchanged."""
    __tracebackhide__ = True
    real_dump = archive_payload._pg_dump
    real_run = archive_payload.subprocess.run
    snapshots, children = [], []

    def run(command, *args, **kwargs):
        __tracebackhide__ = True
        if Path(command[0]).name == "pg_dump" and "--format=custom" in command:
            env = kwargs.get("env", {})
            if env.get("PGUSER") != role:
                pytest.fail("The real pg_dump child must use the runtime login.")
            if env.get("PGSERVICE") or env.get("PGSERVICEFILE") or env.get("PGOPTIONS"):
                pytest.fail("The pg_dump child must have no inherited identity override.")
            for arg in command[1:]:
                if (arg.startswith(("-U", "-d", "--username", "--dbname", "--role"))
                        or "://" in arg or arg.startswith(("user=", "dbname=", "service="))):
                    pytest.fail("The pg_dump command must have no user or DSN override.")
            children.append(True)
        return real_run(command, *args, **kwargs)

    def dump(destination, snapshot_id, **kwargs):
        __tracebackhide__ = True
        assert_runtime_session(role)
        if archive_payload._postgres_environment().get("PGUSER") != role:
            pytest.fail("The real dump must receive runtime credentials before execution.")
        assert connections["default"].in_atomic_block
        assert isinstance(snapshot_id, str) and snapshot_id
        assert kwargs == {"exclude_operational": True}
        snapshots.append(snapshot_id)
        with monkeypatch.context() as observer:
            observer.setattr(archive_payload.subprocess, "run", run)
            return real_dump(destination, snapshot_id, **kwargs)

    with monkeypatch.context() as observer:
        observer.setattr(archive_payload, "_pg_dump", dump)
        yield snapshots, children
