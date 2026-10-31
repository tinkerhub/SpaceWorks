"""Validate bounded, exact authority before any irreversible byte deletion."""

import json
import re
import uuid

from django.utils import timezone

from .purge_object_closure import _safe_key, tenant_prefixes
from .purge_storage import PurgeStorageRefused

KINDS = {"private", "public_image"}
MAX_KEYS = 100000
MAX_PREFIXES = 4096
MAX_AUTHORITY_BYTES = 8 * 1024 * 1024


def validate_receipt(receipt):
    def refuse():
        raise PurgeStorageRefused("Purge receipt authority is invalid, unsupported or too large.")

    if (type(receipt.source_makerspace_id) is not int
            or not 0 < receipt.source_makerspace_id <= 2147483647
            or type(receipt.schema_version) is not int or receipt.schema_version != 1
            or not isinstance(receipt.auth_generation, uuid.UUID)):
        refuse()
    if any(value is None or not timezone.is_aware(value) for value in (
        receipt.source_purge_started_at, receipt.graph_purged_at,
    )) or receipt.graph_purged_at < receipt.source_purge_started_at:
        refuse()
    origins = receipt.storage_origins
    if (not isinstance(origins, dict) or set(origins) != KINDS
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                   for value in origins.values())):
        refuse()
    keys, prefixes = receipt.exact_keys, receipt.namespace_prefixes
    for rows, limit in ((keys, MAX_KEYS), (prefixes, MAX_PREFIXES)):
        if not isinstance(rows, list) or len(rows) > limit:
            refuse()
        seen = set()
        for row in rows:
            if (not isinstance(row, list) or len(row) != 2
                    or not isinstance(row[0], str) or row[0] not in KINDS
                    or not isinstance(row[1], str) or len(row[1].encode("utf-8")) > 1024):
                refuse()
            pair = tuple(row)
            if pair in seen:
                refuse()
            seen.add(pair)
            _safe_key(row[1].removesuffix("/") if rows is prefixes else row[1])
    for kind, prefix in prefixes:
        if prefix in tenant_prefixes(receipt.source_makerspace_id, kind):
            continue
        # Imported/rollback namespaces are frozen from typed owning rows, never
        # inferred later from a changed configuration or a numeric substring.
        match = re.fullmatch(r"(tenant-imports|(?:staging/)?migrated-objects)/([0-9a-f-]{36})/", prefix)
        if not match or (match[1] == "tenant-imports" and kind != "private"):
            refuse()
        try:
            if str(uuid.UUID(match[2])) != match[2]:
                refuse()
        except ValueError:
            refuse()
    for kind, key in keys:
        if any(kind == pkind and key.startswith(prefix) for pkind, prefix in prefixes):
            continue
        if not (
            (kind == "private" and re.fullmatch(r"bulk-imports/[^\s]+", key))
            or re.fullmatch(r"(?:staging/)?rollback/[0-9a-f-]{36}/" + kind + r"/.+", key)
        ):
            refuse()
    try:
        payload = json.dumps([origins, keys, prefixes], ensure_ascii=True).encode("ascii")
    except (TypeError, ValueError):
        refuse()
    if len(payload) > MAX_AUTHORITY_BYTES:
        refuse()
    return frozenset(tuple(row) for row in keys)
