"""Bounded restore object effects; failures retain copies and recovery fencing."""

from datetime import timedelta
import json
import os
from pathlib import Path

from django.utils import timezone

from apps.backup import object_restore_versions, storage
from apps.backup.models import RestoreRollbackObject
from apps.backup.object_restore import _bucket, _head, _safe_key, _upload_replacement
from apps.backup.object_restore_versions import ObjectRestoreError
from apps.backup.restore_object_proof import require_blocked_restore, verify_source_closure
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace


def _append(path, restore, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": timezone.now().isoformat(),
                                 "restore_id": str(restore.pk), **payload}, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    if not existed:
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _prepare(restore, item, journal):
    kind, key = item["bucket_kind"], _safe_key(item["key"])
    bucket, client = _bucket(kind), storage.client()
    versioned = storage.ensure_versioning_or_quiescence(bucket) == "versioned"
    current = _head(client, bucket, key)
    absent = current is None
    source_version = (current or {}).get("VersionId", "") if versioned else ""
    if versioned and not absent and not source_version:
        raise ObjectRestoreError("A versioned recovery source has no immutable version identity.")
    marker = (object_restore_versions.current_delete_marker_version_id(client, bucket, key)
              if versioned and absent else "")
    copy_key = f"rollback/{restore.pk}/{kind}/{key}" if not versioned and not absent else ""
    if copy_key and _head(client, bucket, copy_key) is not None:
        raise ObjectRestoreError("An unexplained recovery copy already occupies this operation key.")
    row = RestoreRollbackObject.objects.create(
        restore=restore, makerspace_id=item.get("makerspace_id"), bucket_kind=kind,
        module_key=item.get("module_key", ""), source_key=key, copy_key=copy_key,
        source_was_absent=absent, source_absent_marker_version_id=marker,
        source_version_id=source_version, expires_at=timezone.now() + timedelta(days=7),
    )
    _append(journal, restore, {
        "effect": "rollback_intent", "row_id": row.pk, "bucket": bucket,
        "bucket_kind": kind, "makerspace_id": row.makerspace_id,
        "module_key": row.module_key, "source_key": key, "copy_key": copy_key,
        "absent": absent, "source_absent_marker_version_id": marker,
        "source_version_id": source_version,
    })
    if copy_key:
        # Keep incomplete rows/copies on every failure: manual recovery owns cleanup.
        client.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": key},
                           Key=copy_key, MetadataDirective="COPY")
        size = current["ContentLength"]
        maker = Makerspace.objects.filter(pk=row.makerspace_id).first() if row.makerspace_id else None
        if maker:
            limits.add_storage(maker, size)
        row.size_bytes = size
        row.save(update_fields=("size_bytes",))
        _append(journal, restore, {
            "effect": "rollback_copy_created", "row_id": row.pk, "size_bytes": size,
            "metadata": current.get("Metadata", {}),
            "content_type": current.get("ContentType", ""),
            "headers": {name: str(current[name]) for name in storage.RESTORABLE_HEADERS
                        if current.get(name) not in (None, "")},
        })
    return row


def restore_objects(restore, bundle_root, manifest, journal_path):
    require_blocked_restore(restore)
    if manifest != restore.archive.manifest:
        raise ObjectRestoreError("Replacement manifest differs from the selected registered archive.")
    verify_source_closure(manifest)
    root = Path(bundle_root).resolve()
    if Path(journal_path).exists():
        raise ObjectRestoreError("Recovery swap journal already exists; automatic effect replay is refused.")
    # Persist an empty complete journal even when the manifest has no live objects.
    descriptor = os.open(journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent_fd = os.open(Path(journal_path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    for item in manifest.get("storage", {}).get("objects", ()):
        key, kind = _safe_key(item["key"]), item["bucket_kind"]
        if item.get("retention_state") == "expired":
            storage.assert_object_absent(_bucket(kind), key)
            storage.assert_object_absent(_bucket(kind), f"staging/{key}")
            continue
        source = (root / "objects" / kind / key).resolve()
        if root not in source.parents or not source.is_file():
            raise ObjectRestoreError("The admitted replacement bytes are missing or unsafe.")
        row = _prepare(restore, item, journal_path)
        row.replacement_version_id = _upload_replacement(item, source)
        row.save(update_fields=("replacement_version_id",))
        _append(journal_path, restore, {"effect": "replacement_written", "row_id": row.pk,
                                      "version_id": row.replacement_version_id})
