"""Settings-free pre-effect admission of complete object readback facts.

This validates the selected manifest and sealed local bytes. It does not sign
historical captures or replace source ownership/closure verification after SQL.
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
from pathlib import Path, PurePosixPath
import re
import stat


class RestoreManifestFactsError(ValueError):
    pass


FIELDS = frozenset({
    "bucket_kind", "key", "makerspace_id", "module_key", "version_id",
    "size", "sha256", "metadata", "content_type", "headers",
})
RETENTION = frozenset({"retention_state", "object_expired_at", "expired_size_bytes"})
HEADERS = frozenset({
    "CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage",
    "ContentType", "Expires", "WebsiteRedirectLocation",
})


def _refuse():
    raise RestoreManifestFactsError("The complete object readback facts are unavailable or invalid.")


def _key(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or any(c in value for c in "\\\x00"):
        _refuse()
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        _refuse()
    return value


def _stamp(value, *, http=False):
    if not isinstance(value, str):
        _refuse()
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        if not http:
            _refuse()
        stamp = parsedate_to_datetime(value)
    if stamp.tzinfo is None:
        _refuse()


def _headers(item):
    metadata, headers = item["metadata"], item["headers"]
    if not isinstance(metadata, dict) or not isinstance(headers, dict) or set(headers) - HEADERS:
        _refuse()
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in metadata.items()):
        _refuse()
    if len({key.lower() for key in metadata}) != len(metadata):
        _refuse()
    if any(not isinstance(value, str) for value in headers.values()):
        _refuse()
    if "ContentType" in headers and headers["ContentType"] != item["content_type"]:
        _refuse()
    if "Expires" in headers:
        _stamp(headers["Expires"], http=True)


def _payload(root, item):
    path = root / "objects" / item["bucket_kind"] / item["key"]
    if item.get("retention_state") == "expired":
        if path.exists() or path.is_symlink():
            _refuse()
        return
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            _refuse()
    facts = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1 or facts.st_size != item["size"]:
        _refuse()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != item["sha256"]:
        _refuse()


def validate_restore_object_facts(manifest, bundle_root=None):
    """Require all facts before quiescence; optionally hash sealed bundle bytes."""
    try:
        if not isinstance(manifest, dict) or not isinstance(manifest.get("storage"), dict):
            _refuse()
        storage = manifest["storage"]
        modes = storage.get("consistency")
        if (not isinstance(modes, dict) or set(modes) != {"private", "public_image"}
                or any(mode not in {"versioned", "quiesced"} for mode in modes.values())
                or not isinstance(storage.get("objects"), list)):
            _refuse()
        root = Path(bundle_root) if bundle_root is not None else None
        if root is not None and (not root.is_dir() or root.is_symlink()):
            _refuse()
        seen = set()
        for item in storage["objects"]:
            if not isinstance(item, dict):
                _refuse()
            expired = item.get("retention_state") == "expired"
            optional = {"canonical_component"} if "canonical_component" in item else set()
            if set(item) != FIELDS | optional | (RETENTION if expired else set()):
                _refuse()
            kind, key = item["bucket_kind"], _key(item["key"])
            if kind not in modes or (kind, key) in seen:
                _refuse()
            seen.add((kind, key))
            if "canonical_component" in item and item["canonical_component"] != "main":
                _refuse()
            maker = item["makerspace_id"]
            if maker is not None and (type(maker) is not int or maker <= 0):
                _refuse()
            if (not isinstance(item["module_key"], str) or len(item["module_key"]) > 64
                    or not isinstance(item["content_type"], str)
                    or (item["version_id"] is not None and not isinstance(item["version_id"], str))
                    or type(item["size"]) is not int or item["size"] < 0):
                _refuse()
            _headers(item)
            if expired:
                if (kind != "private" or item["size"] != 0 or item["sha256"] != ""
                        or item["version_id"] is not None or item["metadata"] != {}
                        or item["headers"] != {} or item["content_type"] != ""):
                    _refuse()
                _stamp(item["object_expired_at"])
                prior_size = item["expired_size_bytes"]
                if prior_size is not None and (type(prior_size) is not int or prior_size < 0):
                    _refuse()
            elif (not item["content_type"] or not isinstance(item["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
                _refuse()
            if root is not None:
                _payload(root, item)
        return len(seen)
    except RestoreManifestFactsError:
        raise
    except (OSError, KeyError, ValueError, TypeError, AttributeError, OverflowError):
        _refuse()
