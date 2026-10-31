"""Restore-only closure and streamed readback; capture scanners stay unchanged."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import hmac

from django.conf import settings

from apps.backup import storage
from apps.backup.full_format import FULL_FORMAT
from apps.backup.object_ownership import MAIN_COMPONENT
from apps.backup.object_reference_capture import build_object_ownership_plan
from apps.backup.object_restore import _bucket
from apps.backup.object_restore_versions import ObjectRestoreError


def require_blocked_restore(restore):
    from apps.backup.host_marker import MarkerState, read_marker

    marker = read_marker(getattr(settings, "SPACEWORKS_HOST_MARKER_PATH",
                                 "/run/spaceworks-host/restore-marker.json"))
    operation = marker.operation
    if (marker.state != MarkerState.RESTORE_BLOCKED or operation is None
            or operation.restore_id != str(restore.pk)
            or operation.artifact_sha256 != restore.archive.archive_sha256
            or (restore.archive.manifest.get("format") == FULL_FORMAT
                and operation.capture_id != restore.archive.manifest.get("capture_id"))):
        raise ObjectRestoreError("Object recovery requires the exact root-blocked restore operation.")
    return marker


def manifest_objects(manifest):
    objects = {}
    for item in manifest.get("storage", {}).get("objects", ()):
        identity = (item["bucket_kind"], item["key"])
        if identity in objects:
            raise ObjectRestoreError("The admitted object manifest repeats a key.")
        objects[identity] = item
    return objects


def _ownership(item):
    value = {name: item.get(name) for name in ("makerspace_id", "module_key")}
    if item.get("retention_state") == "expired":
        value.update({name: item.get(name) for name in (
            "retention_state", "object_expired_at", "expired_size_bytes"
        )})
    return value


def verify_source_closure(manifest, *, extra_references=()):
    """Compare complete source references, including archived rollback copies."""
    objects = manifest_objects(manifest)
    if manifest.get("format") == FULL_FORMAT:
        plan = build_object_ownership_plan(())
        extras = {reference.site: reference for reference in extra_references}
        if len(extras) != len(extra_references):
            raise ObjectRestoreError("Recovery-only references repeat a journal identity.")
        retained = []
        for reference in plan.references:
            expected = extras.pop(reference.site, None)
            if expected is not None and reference != expected:
                raise ObjectRestoreError("Recovery-only ownership differs from its exact journal row.")
            if expected is None:
                retained.append(reference)
        if extras:
            raise ObjectRestoreError("A journal-authorized recovery reference is missing.")
        from apps.backup.object_ownership import ObjectOwnershipPlan

        closure = ObjectOwnershipPlan(retained, ()).closure(MAIN_COMPONENT)
    else:
        from apps.backup.archive_objects import object_closure
        from apps.backup.models import RestoreRollbackObject

        closure = object_closure()
        for reference in extra_references:
            row_id = reference.site.split(":")[1]
            row = RestoreRollbackObject.objects.get(pk=row_id)
            fact = closure.get(reference.bucket_kind, {}).pop(reference.object_key, None)
            if fact != {"makerspace_id": row.makerspace_id, "module_key": row.module_key}:
                raise ObjectRestoreError("Historical recovery copy ownership differs from its exact row.")
    actual = {
        (kind, key): _ownership(value)
        for kind, entries in closure.items() for key, value in entries.items()
    }
    expected = {identity: _ownership(item) for identity, item in objects.items()}
    if actual != expected:
        raise ObjectRestoreError("Restored database object closure differs from admitted source ownership.")
    return objects


def _header(value, name):
    if name == "Expires" and value:
        if not isinstance(value, datetime):
            try:
                value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                value = parsedate_to_datetime(str(value))
        if value.tzinfo is None:
            raise ObjectRestoreError("Object expiry header lacks its timezone.")
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "")


def stream_readback(item, *, required_sha256=True):
    """GET current bytes only; HEAD/ETag and retained versions cannot pass."""
    body = None
    try:
        response = storage.client().get_object(
            Bucket=_bucket(item["bucket_kind"]), Key=item["key"],
        )
        body = response["Body"]
        metadata = {str(key).lower(): str(value) for key, value in response.get("Metadata", {}).items()}
        expected_metadata = {str(key).lower(): str(value) for key, value in item.get("metadata", {}).items()}
        if metadata != expected_metadata:
            raise ObjectRestoreError("Restored object metadata differs from its captured facts.")
        if _header(response.get("ContentType"), "ContentType") != item.get("content_type", ""):
            raise ObjectRestoreError("Restored object content type differs from its captured facts.")
        for name, value in item.get("headers", {}).items():
            if _header(response.get(name), name) != _header(value, name):
                raise ObjectRestoreError("Restored object required headers differ from captured facts.")
        size, digest = 0, hashlib.sha256()
        while chunk := body.read(1024 * 1024):
            size += len(chunk)
            if size > item["size"]:
                raise ObjectRestoreError("Restored object exceeds its captured size.")
            digest.update(chunk)
        if size != item["size"] or (required_sha256 and not hmac.compare_digest(
            digest.hexdigest(), item["sha256"]
        )):
            raise ObjectRestoreError("Restored object bytes differ from their captured facts.")
    except ObjectRestoreError:
        raise
    except Exception as exc:
        raise ObjectRestoreError("A restored object could not be read and verified.") from exc
    finally:
        if body is not None:
            body.close()


def verify_restored_objects(restore, manifest, journal_path):
    from apps.backup.restore_journal_proof import recovery_references

    require_blocked_restore(restore)
    admitted = manifest_objects(manifest)
    references, copies = recovery_references(restore, journal_path, admitted)
    if any((ref.bucket_kind, ref.object_key) in admitted for ref in references):
        raise ObjectRestoreError("A recovery copy conflicts with an admitted source object.")
    objects = verify_source_closure(manifest, extra_references=references)
    for item in objects.values():
        if item.get("retention_state") == "expired":
            bucket = _bucket(item["bucket_kind"])
            storage.assert_object_absent(bucket, item["key"])
            storage.assert_object_absent(bucket, f"staging/{item['key']}")
        else:
            stream_readback(item)
    for item in copies:
        # Local recovery copies have exact private journal facts, no source signature.
        stream_readback(item, required_sha256=False)
    return len(objects)
