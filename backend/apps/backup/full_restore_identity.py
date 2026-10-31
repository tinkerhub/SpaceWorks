"""Settings-free, fixed target identity preservation for in-place signed-full restore."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import re

from apps.backup.database_identity import (
    DatabaseEndpoint,
    DatabaseIdentityError,
    _system_identifier,
    _tls_identity,
    query_live_database_identity,
)
from apps.backup.full_format import FULL_FORMAT
from apps.backup.full_source_identity import canonical_uuid, validate_server_identity
from apps.backup.host_marker import MarkerStage, MarkerState, _operation, read_marker


MAX_CONTROL_BYTES = 65536
CONTROL_FIELDS = frozenset({"full_target_identity"})
OPERATION_FIELD = "restore_operation"


def _refuse():
    raise DatabaseIdentityError("Signed-full target database identity preservation refused.")


def _timestamp(value):
    if not isinstance(value, str) or len(value) != 32:
        _refuse()
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        _refuse()
    if stamp.isoformat(timespec="microseconds") != value:
        _refuse()
    return stamp


def validate_target_record(record):
    try:
        if not isinstance(record, dict) or set(record) != {"format", "identity", "row"}:
            _refuse()
        if record["format"] != FULL_FORMAT:
            _refuse()
        identity, row = record["identity"], record["row"]
        if not isinstance(identity, dict) or set(identity) != {"name", "oid", "server_identity"}:
            _refuse()
        validate_server_identity(identity["server_identity"])
        if (
            identity["name"] != identity["server_identity"]["endpoint"]["database"]
            or type(identity["oid"]) is not int or not 0 < identity["oid"] < 1 << 32
            or not isinstance(row, dict) or set(row) != {
                "id", "database_uuid", "run_id", "artifact_sha256", "capture_id", "created_at"
            } or type(row["id"]) is not int or row["id"] != 1
        ):
            _refuse()
        canonical_uuid(row["database_uuid"])
        if row["database_uuid"] != identity["server_identity"]["database_uuid"]:
            _refuse()
        if row["run_id"] is None:
            if row["artifact_sha256"] != "" or row["capture_id"] is not None:
                _refuse()
        else:
            canonical_uuid(row["run_id"])
            canonical_uuid(row["capture_id"])
            if not isinstance(row["artifact_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", row["artifact_sha256"]) is None:
                _refuse()
        _timestamp(row["created_at"])
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        _refuse()
    return record


def _read_row(database):
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT id, database_uuid::text, run_id::text, artifact_sha256, "
            "capture_id::text, created_at FROM public.backup_deploymentdatabaseidentity"
        )
        rows = cursor.fetchmany(2)
    if len(rows) != 1:
        _refuse()
    pk, database_uuid, run_id, digest, capture_id, stamp = rows[0]
    return {
        "id": pk, "database_uuid": database_uuid, "run_id": run_id,
        "artifact_sha256": digest, "capture_id": capture_id,
        "created_at": stamp.astimezone(timezone.utc).isoformat(timespec="microseconds"),
    }


def capture_target_identity(database):
    live = query_live_database_identity(database)
    record = validate_target_record({
        "format": FULL_FORMAT,
        "identity": {
            "name": live.endpoint.database, "oid": live.oid,
            "server_identity": live.server_identity(),
        },
        "row": _read_row(database),
    })
    _compare_live(live, record)
    return record


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _refuse()
        result[key] = value
    return result


def read_private_control(stream):
    raw = stream.read(MAX_CONTROL_BYTES + 1)
    try:
        if not raw or len(raw.encode("utf-8")) > MAX_CONTROL_BYTES:
            _refuse()
        control = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(control, dict) or set(control) not in (CONTROL_FIELDS, CONTROL_FIELDS | {OPERATION_FIELD}):
            _refuse()
        validate_target_record(control["full_target_identity"])
        if OPERATION_FIELD in control:
            _operation(control[OPERATION_FIELD])
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _refuse()
    return control


def query_physical_metadata(database):
    """Query physical endpoint before the immutable singleton exists."""
    parameters = database.get_dsn_parameters()
    with database.cursor() as cursor:
        cursor.execute("SELECT current_database(), oid FROM pg_database WHERE datname = current_database()")
        name, oid = cursor.fetchone()
        system = _system_identifier(cursor, autocommit=bool(database.autocommit))
    endpoint = DatabaseEndpoint(
        host=parameters.get("host", ""), port=int(parameters.get("port") or 5432),
        database=name, tls_identity=_tls_identity(parameters),
    )
    return {"name": name, "oid": int(oid), "endpoint": asdict(endpoint), "system_identifier": system}


def _corroborate(*systems):
    if len({value for value in systems if value is not None}) > 1:
        _refuse()


def _compare_live(live, record):
    identity, row = record["identity"], record["row"]
    server = identity["server_identity"]
    if (
        live.endpoint.database != identity["name"] or live.oid != identity["oid"]
        or asdict(live.endpoint) != server["endpoint"]
        or live.database_uuid != row["database_uuid"] or live.run_id != row["run_id"]
        or live.artifact_sha256 != row["artifact_sha256"] or live.capture_id != row["capture_id"]
    ):
        _refuse()
    _corroborate(live.system_identifier, server["system_identifier"])


def verify_target_identity(database, record):
    validate_target_record(record)
    live = query_live_database_identity(database)
    _compare_live(live, record)
    if _read_row(database) != record["row"]:
        _refuse()
    return live


def _bound_target_control(database, control, marker_path, *, require_blocked=False):
    """Validate the fixed target before any identity or grant effect."""
    if database.autocommit:
        _refuse()
    record = validate_target_record(control.get("full_target_identity"))
    marker = read_marker(marker_path)
    if marker.stage != MarkerStage.BOUND or marker.state not in {
        MarkerState.NORMAL, MarkerState.ACKNOWLEDGED_NORMAL, MarkerState.RESTORE_BLOCKED,
    }:
        _refuse()
    if marker.state == MarkerState.RESTORE_BLOCKED and (
        OPERATION_FIELD not in control or marker.operation != _operation(control[OPERATION_FIELD])
    ):
        _refuse()
    if require_blocked and marker.state != MarkerState.RESTORE_BLOCKED:
        _refuse()
    bound = marker.require_bound_database()
    identity, row = record["identity"], record["row"]
    server = identity["server_identity"]
    if (
        bound.server_identity is None or bound.name != identity["name"] or bound.oid != identity["oid"]
        or bound.server_identity["endpoint"] != server["endpoint"]
        or bound.server_identity["database_uuid"] != row["database_uuid"]
    ):
        _refuse()
    physical = query_physical_metadata(database)
    if (
        physical["name"] != bound.name or physical["oid"] != bound.oid
        or physical["endpoint"] != server["endpoint"]
    ):
        _refuse()
    _corroborate(
        physical["system_identifier"], server["system_identifier"],
        bound.server_identity["system_identifier"],
    )
    return record, bound, physical


def verify_legacy_dump_identity(database, record):
    """Check only the exact captured row in a root-owned disposable preview DB."""
    validate_target_record(record)
    if _read_row(database) != record["row"]:
        _refuse()


def verify_legacy_target_identity(database, control, marker_path):
    """Verify an existing same-host identity; never insert, adopt or replace it.

    The root operation record labels the capture local-legacy-operation. Reusing
    the target-record structure here makes no source-signature assertion.
    """
    record, bound, physical = _bound_target_control(
        database, control, marker_path, require_blocked=True,
    )
    with database.cursor() as cursor:
        cursor.execute("LOCK TABLE public.backup_deploymentdatabaseidentity IN ACCESS EXCLUSIVE MODE")
    live = verify_target_identity(database, record)
    _corroborate(live.system_identifier, physical["system_identifier"],
                 bound.server_identity["system_identifier"])
    return live


def restore_target_identity(database, control, marker_path):
    """Caller owns the transaction, including grants; any refusal rolls it back."""
    record, bound, physical = _bound_target_control(database, control, marker_path)
    row = record["row"]
    with database.cursor() as cursor:
        cursor.execute("LOCK TABLE public.backup_deploymentdatabaseidentity IN ACCESS EXCLUSIVE MODE")
        cursor.execute("SELECT EXISTS (SELECT 1 FROM public.backup_deploymentdatabaseidentity)")
        if cursor.fetchone()[0]:
            _refuse()
        cursor.execute(
            "INSERT INTO public.backup_deploymentdatabaseidentity "
            "(id, database_uuid, run_id, artifact_sha256, capture_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [row["id"], row["database_uuid"], row["run_id"], row["artifact_sha256"],
             row["capture_id"], _timestamp(row["created_at"])],
        )
    live = verify_target_identity(database, record)
    _corroborate(
        live.system_identifier, physical["system_identifier"],
        bound.server_identity["system_identifier"],
    )
