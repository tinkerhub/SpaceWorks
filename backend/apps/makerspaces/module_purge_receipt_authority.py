"""Bound raw authority before advisory locks, storage, or retained-locator use."""

import json
import re
import uuid

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .module_purge_namespaces import validate_clauses
from .purge_object_closure import _safe_key
from .purge_storage import PurgeStorageRefused

MUTABLE = {"graph_purged_at", "invalidated_at", "invalidation_reason",
           "last_attempt_at", "last_verified_at", "last_error_code"}
REASONS = {"", "module_enabled", "recovery", "tenant_purged"}
ROLLBACK_FIELDS = (
    "id", "restore_id", "makerspace_id", "bucket_kind", "module_key", "source_key",
    "copy_key", "size_bytes", "source_was_absent", "source_absent_marker_version_id",
    "source_version_id", "replacement_version_id", "expires_at",
)


def refuse():
    raise PurgeStorageRefused("Module cleanup authority is invalid, incompatible or too large.")


def bounded_id(value, maximum=9223372036854775807):
    return type(value) is int and 0 < value <= maximum


def procurement_identity(identity):
    match = re.fullmatch(r"procurement:([1-9][0-9]{0,18}):([0-9a-f-]{36})", identity)
    if match is None or int(match[1]) > 9223372036854775807:
        refuse()
    try:
        event = uuid.UUID(match[2])
    except ValueError:
        refuse()
    if not event.int or str(event) != match[2]:
        refuse()
    return match[1], match[2]


def validate_receipt(receipt):
    from .module_purge_plans import BY_KEY

    if (not bounded_id(receipt.source_makerspace_id, 2147483647)
            or type(receipt.schema_version) is not int or receipt.schema_version != 1
            or not isinstance(receipt.module_key, str) or receipt.module_key not in BY_KEY
            or not isinstance(receipt.id, uuid.UUID)
            or not isinstance(receipt.auth_generation, uuid.UUID)
            or not isinstance(receipt.source_public_code, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", receipt.source_public_code)
            or not isinstance(receipt.graph_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", receipt.graph_digest)):
        refuse()
    for name in {"source_created_at", "intent_created_at"} | (MUTABLE - {
        "invalidation_reason", "last_error_code",
    }):
        value = getattr(receipt, name)
        if value is None and name not in {"source_created_at", "intent_created_at"}:
            continue
        try:
            if value is None or not timezone.is_aware(value):
                refuse()
        except (AttributeError, TypeError):
            refuse()
    if (receipt.source_created_at > receipt.intent_created_at
            or (receipt.graph_purged_at and receipt.graph_purged_at < receipt.intent_created_at)
            or receipt.last_error_code not in {"", "cleanup_unconfirmed"}
            or receipt.invalidation_reason not in REASONS
            or (receipt.invalidated_at is None) != (receipt.invalidation_reason == "")):
        refuse()
    for name in ("invalidated_at", "last_attempt_at", "last_verified_at"):
        value = getattr(receipt, name)
        if value is not None and value < receipt.intent_created_at:
            refuse()
    if receipt.last_verified_at is not None and (
        receipt.graph_purged_at is None or receipt.last_attempt_at is None
        or receipt.graph_purged_at > receipt.last_verified_at or receipt.last_verified_at > receipt.last_attempt_at
    ):
        refuse()
    origins = receipt.storage_origins
    if (not isinstance(origins, dict) or set(origins) != {"private", "public_image"}
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in origins.values())):
        refuse()
    values = [receipt.exact_keys, receipt.namespace_clauses, receipt.holder_sites,
              receipt.charge_obligations, receipt.rollback_bindings]
    try:
        if len(json.dumps(values, ensure_ascii=True).encode("ascii")) > 8 * 1024 * 1024:
            refuse()
    except (TypeError, ValueError, OverflowError):
        refuse()
    validate_clauses(receipt.namespace_clauses, receipt.module_key, receipt.source_makerspace_id)
    pairs = _pairs(receipt.exact_keys)
    sites = receipt.holder_sites
    if not isinstance(sites, list) or len(sites) > 100000:
        refuse()
    seen = set()
    for row in sites:
        if (not isinstance(row, list) or len(row) != 5
                or not all(isinstance(v, str) and 0 < len(v) <= 1024 for v in row)
                or not re.fullmatch(r"[a-z_]+\.[A-Za-z][A-Za-z0-9]*", row[0])
                or not re.fullmatch(r"[A-Za-z0-9-]{1,40}", row[1])
                or row[2] not in {"object_key", "image_key", "avatar_key", "source_key", "copy_key"}
                or (row[3], row[4]) not in pairs or tuple(row) in seen):
            refuse()
        seen.add(tuple(row))
    _validate_obligations(receipt.charge_obligations, pairs)
    _validate_rollback(receipt.rollback_bindings, receipt)
    from .module_purge_sites import validate_sites

    validate_sites(receipt)
    # Exact keys outside a grammar require an immutable, typed holder site.
    from .module_purge_namespaces import owns_key

    site_keys = {(row[3], row[4]) for row in sites}
    for kind, key in pairs:
        if not owns_key(receipt.namespace_clauses, kind, key):
            final = key.removeprefix("staging/")
            if (kind, key) not in site_keys and (kind, final) not in site_keys:
                refuse()
    return frozenset(pairs)


def _pairs(rows):
    if not isinstance(rows, list) or len(rows) > 100000:
        refuse()
    seen = set()
    for row in rows:
        if (not isinstance(row, list) or len(row) != 2
                or not isinstance(row[0], str) or row[0] not in {"private", "public_image"}
                or not isinstance(row[1], str) or len(row[1].encode()) > 1024):
            refuse()
        _safe_key(row[1])
        if row[1].startswith("staging/staging/") or tuple(row) in seen:
            refuse()
        seen.add(tuple(row))
    return seen


def _validate_obligations(rows, pairs):
    if not isinstance(rows, list) or len(rows) > 100000:
        refuse()
    seen = set()
    for row in rows:
        if (not isinstance(row, list) or len(row) != 4 or not isinstance(row[0], str)
                or not (row[0].startswith("procurement:") or re.fullmatch(
                    r"(?:public|maintenance|service|certificate|rollback):[A-Za-z0-9:-]{1,128}", row[0]))
                or not isinstance(row[1], str) or not isinstance(row[2], str)
                or (row[1], row[2]) not in pairs or type(row[3]) is not int
                or not 0 <= row[3] <= 9223372036854775807 or row[0] in seen):
            refuse()
        if row[0].startswith("procurement:"):
            procurement_identity(row[0])
            if row[1] != "private" or row[3] <= 0:
                refuse()
        seen.add(row[0])
    if sum(row[3] for row in rows) > 9223372036854775807:
        refuse()


def _validate_rollback(rows, receipt):
    if not isinstance(rows, list) or len(rows) > 100000:
        refuse()
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != set(ROLLBACK_FIELDS)
                or not bounded_id(row["id"]) or row["id"] in seen
                or row["makerspace_id"] != receipt.source_makerspace_id
                or row["module_key"] != receipt.module_key
                or type(row["size_bytes"]) is not int or not 0 <= row["size_bytes"] <= 9223372036854775807
                or type(row["source_was_absent"]) is not bool):
            refuse()
        try:
            if (str(uuid.UUID(row["restore_id"])) != row["restore_id"]
                    or not timezone.is_aware(parse_datetime(row["expires_at"]))):
                refuse()
        except (TypeError, ValueError, AttributeError):
            refuse()
        for field in ("source_key", "copy_key", "source_absent_marker_version_id",
                      "source_version_id", "replacement_version_id"):
            if not isinstance(row[field], str) or len(row[field].encode()) > 1024:
                refuse()
        if not isinstance(row["bucket_kind"], str) or row["bucket_kind"] not in {"private", "public_image"}:
            refuse()
        _safe_key(row["source_key"])
        if row["copy_key"]:
            _safe_key(row["copy_key"])
            if row["copy_key"] != f"rollback/{row['restore_id']}/{row['bucket_kind']}/{row['source_key']}":
                refuse()
        elif row["size_bytes"]:
            refuse()
        seen.add(row["id"])


def validate_transition(previous, current):
    if any(getattr(previous, f.attname) != getattr(current, f.attname)
           for f in current._meta.concrete_fields if f.name not in MUTABLE):
        refuse()
    for name in ("graph_purged_at", "invalidated_at", "invalidation_reason"):
        old = getattr(previous, name)
        if old and old != getattr(current, name):
            refuse()
    for name in ("last_attempt_at", "last_verified_at"):
        old, new = getattr(previous, name), getattr(current, name)
        if old and (new is None or new < old):
            refuse()
