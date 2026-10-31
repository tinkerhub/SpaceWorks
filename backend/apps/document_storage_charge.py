"""Strict, immutable local debit facts for the two removable document types."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import re
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware

from apps.evidence.quota import local_accounting_database_id
from apps.evidence.storage import StorageUnavailable
from apps.makerspaces.purge_intent import storage_origins


CHARGE_ACTIONS = {
    "warranty.warrantydocument": "warranty.document_added",
    "procurement.tobuyreceipt": "procurement.receipt_added",
}
PROOF_FIELDS = frozenset({
    "version", "bytes", "accounting_database_id", "storage_origin",
    "object_key_sha256", "row_created_at",
})


class DocumentChargeProofUnavailable(StorageUnavailable):
    """The document debit cannot be recorded with valid local proof."""


def canonical_uuid(value):
    if type(value) is not str:
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return bool(parsed.int) and str(parsed) == value


def canonical_row_time(value):
    if type(value) is not str:
        return False
    try:
        parsed = parse_datetime(value)
        return parsed is not None and is_aware(parsed) and parsed.isoformat() == value
    except (ValueError, TypeError):
        return False


def current_context():
    """Read, never create/cache, the local DB identity and private origin."""
    try:
        database_id = local_accounting_database_id()
        origin = storage_origins()["private"]
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
        return None
    if (not canonical_uuid(database_id) or type(origin) is not str
            or re.fullmatch(r"[0-9a-f]{64}", origin) is None):
        return None
    return database_id, origin


def valid_target(makerspace_id, target_type, target_id, object_key, row_created_at):
    return (
        type(makerspace_id) is int and makerspace_id > 0
        and type(target_type) is str and target_type in CHARGE_ACTIONS
        and type(target_id) is str and re.fullmatch(r"[1-9][0-9]*", target_id) is not None
        and type(object_key) is str and bool(object_key)
        and canonical_row_time(row_created_at)
    )


@dataclass(frozen=True)
class ChargeProof:
    makerspace_id: int
    target_type: str
    target_id: str
    object_key: str
    row_created_at: str
    size_bytes: int
    accounting_database_id: str
    storage_origin: str
    charge_event_uuid: str

    def metadata(self):
        return {
            "version": 1, "bytes": self.size_bytes,
            "accounting_database_id": self.accounting_database_id,
            "storage_origin": self.storage_origin,
            "object_key_sha256": sha256(self.object_key.encode()).hexdigest(),
            "row_created_at": self.row_created_at,
        }


def charge_metadata(document, *, makerspace_id, size_bytes):
    """After add_storage is True, build proof INSIDE its outer atomic block.

    Missing context must raise through atomic exit so the actual debit, row and
    existing added audit event all roll back together.
    """
    context = current_context()
    created_at = document.created_at
    row_time = created_at.isoformat() if isinstance(created_at, datetime) else None
    if (context is None or type(size_bytes) is not int or size_bytes <= 0
            or not valid_target(makerspace_id, document._meta.label_lower,
                                str(document.pk), document.object_key, row_time)):
        raise DocumentChargeProofUnavailable
    database_id, origin = context
    return {
        "version": 1, "bytes": size_bytes,
        "accounting_database_id": database_id, "storage_origin": origin,
        "object_key_sha256": sha256(document.object_key.encode()).hexdigest(),
        "row_created_at": row_time,
    }


def parse_charge(event, *, makerspace_id, target_type, target_id, object_key,
                 row_created_at, context):
    """Untrusted legacy/import metadata cannot establish a local debit."""
    meta = event.meta
    if context is None or not isinstance(meta, dict):
        return None
    database_id, origin = context
    event_uuid = str(event.event_uuid)
    if (
        not valid_target(makerspace_id, target_type, target_id, object_key, row_created_at)
        or event.makerspace_id != makerspace_id
        or event.target_type != target_type or event.target_id != target_id
        or event.action != CHARGE_ACTIONS[target_type]
        or not canonical_uuid(event_uuid)
        or type(meta.get("version")) is not int or meta["version"] != 1
        or type(meta.get("bytes")) is not int or meta["bytes"] <= 0
        or meta.get("accounting_database_id") != database_id
        or meta.get("storage_origin") != origin
        or meta.get("object_key_sha256") != sha256(object_key.encode()).hexdigest()
        or meta.get("row_created_at") != row_created_at
    ):
        return None
    return ChargeProof(
        makerspace_id, target_type, target_id, object_key, row_created_at,
        meta["bytes"], database_id, origin, event_uuid,
    )
