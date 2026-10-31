"""Selected archive facts retained outside an in-place database replacement."""

from datetime import datetime
import json
import os
import re
import uuid

from apps.backup.full_format import FULL_FORMAT
from apps.backup.outer_manifest import manifest_digest


ARCHIVE_FIELDS = frozenset({
    "archive_id", "manifest_sha256", "archive_sha256", "size_bytes",
    "object_key", "completed_at", "expires_at",
})
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError
    return stamp


def validate_archive_record(record, manifest, archive_id):
    """A changed file cannot select a different signed archive after replacement."""
    try:
        if not isinstance(record, dict) or set(record) != ARCHIVE_FIELDS:
            raise ValueError
        identifier = str(uuid.UUID(str(archive_id)))
        if (
            manifest.get("format") != FULL_FORMAT
            or record["archive_id"] != identifier
            or manifest["archive_id"] != identifier
            or record["manifest_sha256"] != manifest_digest(manifest)
            or not isinstance(record["archive_sha256"], str)
            or _DIGEST.fullmatch(record["archive_sha256"]) is None
            or type(record["size_bytes"]) is not int or record["size_bytes"] <= 0
            or record["object_key"] != f"backup-archives/deployment/{identifier}.tar.age"
            or _timestamp(record["expires_at"]) <= _timestamp(record["completed_at"])
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise RuntimeError("The selected signed-full archive control facts changed.") from exc
    return record


def capture_archive_record(archive):
    record = {
        "archive_id": str(archive.pk),
        "manifest_sha256": manifest_digest(archive.manifest),
        "archive_sha256": archive.archive_sha256,
        "size_bytes": archive.size_bytes,
        "object_key": archive.object_key,
        "completed_at": archive.completed_at.isoformat() if archive.completed_at else None,
        "expires_at": archive.expires_at.isoformat() if archive.expires_at else None,
    }
    return validate_archive_record(record, archive.manifest, archive.pk)


def apply_archive_record(archive, record):
    for name in ("archive_sha256", "size_bytes", "object_key"):
        setattr(archive, name, record[name])
    for name in ("completed_at", "expires_at"):
        setattr(archive, name, _timestamp(record[name]))
    archive.download_token_digest = ""
    archive.download_token_expires_at = None
    archive.download_token_consumed_at = None


def write_private_json(path, payload):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
