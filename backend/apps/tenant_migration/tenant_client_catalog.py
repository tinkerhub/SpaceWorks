"""Exact, bounded metadata schema for the encrypted source-client catalog."""

import hashlib
import json
import re
from uuid import UUID

from .tenant_restore_types import TenantRestoreRefused

SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEADER_FIELDS = {"version", "capture_id", "source_deployment_id", "source_makerspace_id", "entries", "sha256"}
ENTRY_FIELDS = {
    "source_client_ref", "label", "client_type", "rate_limit_tier", "is_active",
    "stored_scopes", "stored_origins", "canonical_scopes", "canonical_origins",
    "eligible_for_reissue", "ineligibility_reason", "source_entry_sha256",
}
MAX_CATALOG_BYTES = 8 * 1024 * 1024
MAX_CLIENTS = 10000
MAX_DECLARATIONS = 128


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _text(value, limit, *, nonempty=False):
    return (isinstance(value, str) and len(value) <= limit
            and (not nonempty or bool(value.strip()))
            and not any(ord(c) < 32 or 0x7F <= ord(c) <= 0x9F
                        or 0xD800 <= ord(c) <= 0xDFFF for c in value))


def validate_catalog_identity(capture_id, source_deployment_id, source_makerspace_id):
    try:
        if (not isinstance(capture_id, str) or str(UUID(capture_id)) != capture_id
                or not _text(source_deployment_id, 255, nonempty=True)
                or str(UUID(source_deployment_id)) != source_deployment_id
                or type(source_makerspace_id) is not int or source_makerspace_id <= 0):
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise TenantRestoreRefused("The source API-client catalog identity is invalid.") from exc


def _safe_declaration(value):
    # Preserve invalid-but-representable declarations for classification. Objects,
    # nested arrays and unbounded strings are refused without echoing their bytes.
    if value is None or type(value) in {bool, int}:
        return type(value) is not int or -(2**63) <= value < 2**63
    if isinstance(value, str):
        return _text(value, 2048)
    return (isinstance(value, list) and len(value) <= MAX_DECLARATIONS
            and all(_text(item, 2048) for item in value))


def _safe_origins(value):
    declarations = value if isinstance(value, list) else [value]
    return _safe_declaration(value) and all(
        not isinstance(item, str) or "@" not in item for item in declarations
    )


def classify_entry(entry):
    """Vocabulary validation classifies source authority; it never grants it."""
    from apps.apiclients.origin_validation import validate_exact_origins
    from apps.apiclients.scope_grants import validate_grantable_scopes

    scopes, origins = [], []
    reason = ""
    if not _text(entry["label"], 200, nonempty=True):
        reason = "invalid_label"
    elif entry["client_type"] not in {"browser", "server"}:
        reason = "invalid_client_type"
    elif entry["rate_limit_tier"] not in {"public", "standard", "trusted"}:
        reason = "invalid_rate_limit_tier"
    elif type(entry["is_active"]) is not bool:
        reason = "invalid_active_flag"
    try:
        raw = entry["stored_scopes"]
        if not isinstance(raw, list):
            raise ValueError
        scopes = validate_grantable_scopes(raw, privileged=True)
    except ValueError:
        reason = reason or "invalid_scopes"
    try:
        origins = validate_exact_origins(entry["stored_origins"])
    except ValueError:
        reason = reason or "invalid_origins"
    if entry["is_active"] is False:
        reason = reason or "inactive"
    return {"canonical_scopes": scopes, "canonical_origins": origins,
            "eligible_for_reissue": not reason, "ineligibility_reason": reason}


def validate_client_catalog(catalog, *, capture_id=None, source_deployment_id=None,
                            source_makerspace_id=None):
    try:
        if (not isinstance(catalog, dict) or set(catalog) != HEADER_FIELDS
                or type(catalog["version"]) is not int or catalog["version"] != 1):
            raise ValueError
        validate_catalog_identity(catalog["capture_id"], catalog["source_deployment_id"], catalog["source_makerspace_id"])
        bindings = {"capture_id": capture_id, "source_deployment_id": source_deployment_id,
                    "source_makerspace_id": source_makerspace_id}
        if any(expected is not None and catalog[name] != expected for name, expected in bindings.items()):
            raise ValueError
        entries = catalog["entries"]
        if not isinstance(entries, list) or len(entries) > MAX_CLIENTS:
            raise ValueError
        refs = []
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS
                    or not _is_sha256(entry["source_client_ref"])
                    or not _text(entry["label"], 200)
                    or not _text(entry["client_type"], 20)
                    or not _text(entry["rate_limit_tier"], 20)
                    or not _safe_declaration(entry["stored_scopes"])
                    or not _safe_origins(entry["stored_origins"])
                    or type(entry["is_active"]) is not bool
                    or type(entry["eligible_for_reissue"]) is not bool):
                raise ValueError
            expected = classify_entry(entry)
            if any(entry[name] != value for name, value in expected.items()):
                raise ValueError
            if (not _is_sha256(entry["source_entry_sha256"])
                    or _digest({key: value for key, value in entry.items() if key != "source_entry_sha256"}) != entry["source_entry_sha256"]):
                raise ValueError
            refs.append(entry["source_client_ref"])
        if len(_canonical(catalog).encode("utf-8")) > MAX_CATALOG_BYTES:
            raise ValueError
        if refs != sorted(set(refs)) or not _is_sha256(catalog["sha256"]) or _digest(entries) != catalog["sha256"]:
            raise ValueError
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError) as exc:
        raise TenantRestoreRefused("The source API-client catalog is invalid or changed.") from exc
    return catalog
