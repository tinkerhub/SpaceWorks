"""Read-only client metadata capture from the immutable source database alias."""

import hashlib
from uuid import UUID

from .tenant_client_catalog import (
    MAX_CATALOG_BYTES, MAX_CLIENTS, _canonical, _digest, _safe_declaration, _safe_origins, _text, classify_entry,
    validate_catalog_identity, validate_client_catalog,
)
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_restore_types import TenantRestoreRefused

SOURCE_FIELDS = ("pk", "label", "client_type", "rate_limit_tier", "is_active", "scopes", "allowed_origins")


def build_source_client_catalog(capture_id, source_deployment_id, makerspace, using="default"):
    from apps.apiclients.models import ApiClient

    owner = getattr(makerspace, "pk", makerspace)
    capture_id = str(capture_id)
    if isinstance(source_deployment_id, UUID):
        source_deployment_id = str(source_deployment_id)
    try:
        validate_catalog_identity(capture_id, source_deployment_id, owner)
        # A values allowlist prevents model construction and all credential getters.
        rows = ApiClient.objects.using(using).filter(makerspace_id=owner).values(*SOURCE_FIELDS)[:MAX_CLIENTS + 1]
        entries = []
        encoded_size = 0
        for row in rows:
            ref = hashlib.sha256(
                f"lane-d-source-client-v1\0{capture_id}\0{source_deployment_id}\0{owner}\0{row['pk']}".encode("utf-8")
            ).hexdigest()
            entry = {
                "source_client_ref": ref, "label": row["label"],
                "client_type": row["client_type"], "rate_limit_tier": row["rate_limit_tier"],
                "is_active": row["is_active"], "stored_scopes": row["scopes"],
                "stored_origins": row["allowed_origins"],
            }
            # Validate raw representations before any vocabulary/parser work.
            if (not _text(entry["label"], 200) or not _text(entry["client_type"], 20)
                    or not _text(entry["rate_limit_tier"], 20)
                    or not _safe_declaration(entry["stored_scopes"])
                    or not _safe_origins(entry["stored_origins"])):
                raise TenantRestoreRefused("Source client metadata cannot be represented safely.")
            entry.update(classify_entry(entry))
            entry["source_entry_sha256"] = _digest(entry)
            encoded_size += len(_canonical(entry).encode("utf-8"))
            if encoded_size > MAX_CATALOG_BYTES:
                raise TenantRestoreRefused("The source client catalog exceeds its metadata budget.")
            entries.append(entry)
        entries.sort(key=lambda entry: entry["source_client_ref"])
        catalog = {"version": 1, "capture_id": capture_id, "source_deployment_id": source_deployment_id,
                   "source_makerspace_id": owner, "entries": entries, "sha256": _digest(entries)}
        return validate_client_catalog(catalog)
    except (TenantRestoreRefused, ValueError, TypeError, UnicodeError) as exc:
        raise TenantDumpVerificationError("The immutable source client metadata is not safely representable.") from exc
