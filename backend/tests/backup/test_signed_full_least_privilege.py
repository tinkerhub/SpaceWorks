"""Real restricted role: UUID source binding survives denied pg_control_system."""

import uuid

import psycopg2
from psycopg2 import sql
import pytest
from django.db import connection

from apps.backup.full_source_identity import capture_source_identity
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from tests.backup.full_backup_privilege_helpers import hardened_control_acl


pytestmark = pytest.mark.django_db(transaction=True)


def test_source_identity_uses_uuid_under_nocreatedb_nosuperuser_without_pg_monitor():
    expected = DeploymentDatabaseIdentity.load()
    role = "stage3_runtime_" + uuid.uuid4().hex
    identifier = sql.Identifier(role)
    with hardened_control_acl(connection) as acl:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOCREATEDB NOSUPERUSER NOINHERIT").format(identifier))
        raw = None
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(identifier))
                cursor.execute(sql.SQL("GRANT SELECT ON backup_deploymentdatabaseidentity TO {}").format(identifier))
            raw = psycopg2.connect(**connection.get_connection_params())
            with raw:
                with raw.cursor() as cursor:
                    cursor.execute(sql.SQL("SET ROLE {}").format(identifier))
                    cursor.execute("SELECT rolcreatedb, rolsuper, pg_has_role(current_user, 'pg_monitor', 'MEMBER') "
                                   "FROM pg_roles WHERE rolname=current_user")
                    assert cursor.fetchone() == (False, False, False)
                    cursor.execute("SELECT has_function_privilege(current_user, "
                                   "'pg_catalog.pg_control_system()', 'EXECUTE')")
                    assert cursor.fetchone() == (False,)
                    cursor.execute("SAVEPOINT expected_permission_denial")
                    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                        cursor.execute("SELECT system_identifier FROM pg_catalog.pg_control_system()")
                    cursor.execute("ROLLBACK TO SAVEPOINT expected_permission_denial")
                    cursor.execute("RELEASE SAVEPOINT expected_permission_denial")
                name, server = capture_source_identity(raw)
                assert name == connection.settings_dict["NAME"]
                assert server["database_uuid"] == str(expected.database_uuid)
                assert server["system_identifier"] is None
                with raw.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    assert cursor.fetchone() == (1,)  # Optional denial did not poison snapshot.
        finally:
            if raw is not None:
                raw.close()
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP OWNED BY {}").format(identifier))
                cursor.execute(sql.SQL("DROP ROLE {}").format(identifier))
    assert acl["after"]["grants"] == acl["before"]["grants"]
