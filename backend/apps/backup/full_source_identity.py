"""Settings-free validation of queried full-capture source facts."""

import re
import uuid

from apps.backup.database_identity import DatabaseIdentityError, query_live_database_identity
from apps.backup.errors import BackupBuildError


def canonical_uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Invalid database identity UUID.")
    return value


def bounded_text(value, maximum=1024, *, empty=False):
    if (
        not isinstance(value, str) or len(value) > maximum
        or (not value and not empty) or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("Invalid database identity string.")
    return value


def validate_server_identity(value):
    if not isinstance(value, dict) or set(value) != {
        "endpoint", "database_uuid", "system_identifier"
    }:
        raise ValueError("Invalid database server identity.")
    canonical_uuid(value["database_uuid"])
    endpoint = value["endpoint"]
    if not isinstance(endpoint, dict) or set(endpoint) != {
        "host", "port", "database", "tls_identity"
    }:
        raise ValueError("Invalid database endpoint.")
    host = bounded_text(endpoint["host"])
    if any(part in host for part in ("://", "@", "=", "?", "#")):
        raise ValueError("Invalid database endpoint host.")
    bounded_text(endpoint["database"], 63)
    if type(endpoint["port"]) is not int or not 0 < endpoint["port"] < 65536:
        raise ValueError("Invalid database endpoint port.")
    tls = bounded_text(endpoint["tls_identity"], 96, empty=True)
    if tls and re.fullmatch(r"verify-(?:ca|full):sha256:[0-9a-f]{64}", tls) is None:
        raise ValueError("Invalid database TLS identity.")
    system = value["system_identifier"]
    if system is not None and (
        not isinstance(system, str) or re.fullmatch(r"[1-9][0-9]{0,19}", system) is None
        or int(system) >= 1 << 64
    ):
        raise ValueError("Invalid database system identifier.")


def validate_source_identity(database, server, major):
    if not isinstance(server, dict) or set(server) != {
        "server_version_num", "endpoint", "database_uuid", "system_identifier"
    }:
        raise ValueError("Invalid full source server identity.")
    version = server["server_version_num"]
    if (
        not isinstance(version, str) or re.fullmatch(r"[1-9][0-9]{5}", version) is None
        or int(version) // 10000 != major
    ):
        raise ValueError("Incoherent full source PostgreSQL version.")
    validate_server_identity({key: value for key, value in server.items() if key != "server_version_num"})
    if database != server["endpoint"]["database"]:
        raise ValueError("Incoherent full source database name.")


def capture_source_identity(database):
    try:
        live = query_live_database_identity(database)
        with database.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version_num')")
            version = cursor.fetchone()[0]
        server = {**live.server_identity(), "server_version_num": version}
        validate_source_identity(live.endpoint.database, server, int(version) // 10000)
        return live.endpoint.database, server
    except (DatabaseIdentityError, ValueError, TypeError, AttributeError) as exc:
        raise BackupBuildError("The queried full source database identity is unavailable or invalid.") from exc
