"""Exact operation journal-to-row proof for new recovery-only object copies."""

import json
import os
import stat
from pathlib import Path

from apps.backup.models import RestoreRollbackObject
from apps.backup.object_ownership import MAIN_COMPONENT, ObjectReference
from apps.backup.object_restore import _bucket
from apps.backup.object_restore_versions import ObjectRestoreError


def recovery_references(restore, journal_path, objects):
    """No prefix/model exemption: consume exact new row identities only."""
    events = {}
    try:
        path = Path(journal_path)
        parent = path.parent.stat(follow_symlinks=False)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            facts = os.fstat(stream.fileno())
            if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
                    or parent.st_mode & 0o022 or not stat.S_ISREG(facts.st_mode)
                    or facts.st_uid != 0 or stat.S_IMODE(facts.st_mode) != 0o444
                    or facts.st_nlink != 1 or facts.st_size > 64 * 1024 * 1024):
                raise ValueError
            lines = stream.read().splitlines()
        for line in lines:
            event = json.loads(line)
            row_id = event["row_id"]
            if type(row_id) is not int or event.get("restore_id") != str(restore.pk):
                raise ValueError
            effect = event.get("effect")
            if effect == "rollback_intent":
                if row_id in events:
                    raise ValueError
                events[row_id] = {"intent": event}
            elif effect in {"rollback_copy_created", "replacement_written"}:
                if row_id not in events or effect in events[row_id]:
                    raise ValueError
                events[row_id][effect] = event
            else:
                raise ValueError
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ObjectRestoreError("The complete recovery swap journal is unavailable or invalid.") from exc
    rows = {row.pk: row for row in RestoreRollbackObject.objects.filter(restore=restore)}
    if set(rows) != set(events):
        raise ObjectRestoreError("Recovery swap journal and persisted row identities differ.")
    live = {identity: item for identity, item in objects.items()
            if item.get("retention_state") != "expired"}
    if {(row.bucket_kind, row.source_key) for row in rows.values()} != set(live):
        raise ObjectRestoreError("Recovery outcomes do not cover the exact admitted live object set.")
    references, copies = [], []
    for identifier, facts in events.items():
        row, intent = rows[identifier], facts["intent"]
        item = live[(row.bucket_kind, row.source_key)]
        if (row.makerspace_id != item.get("makerspace_id")
                or row.module_key != item.get("module_key", "")
                or (row.copy_key and row.copy_key != (
                    f"rollback/{restore.pk}/{row.bucket_kind}/{row.source_key}"
                ))):
            raise ObjectRestoreError("A recovery outcome differs from its admitted source owner/key.")
        checks = {
            "bucket": _bucket(row.bucket_kind), "bucket_kind": row.bucket_kind,
            "makerspace_id": row.makerspace_id, "module_key": row.module_key,
            "source_key": row.source_key, "copy_key": row.copy_key,
            "absent": row.source_was_absent,
            "source_version_id": row.source_version_id,
            "source_absent_marker_version_id": row.source_absent_marker_version_id,
        }
        if any(intent.get(name) != value for name, value in checks.items()):
            raise ObjectRestoreError("Recovery rollback row differs from its operation journal.")
        replacement = facts.get("replacement_written")
        if replacement is None or replacement.get("version_id", "") != row.replacement_version_id:
            raise ObjectRestoreError("A recovery replacement has no complete durable outcome.")
        if not row.copy_key:
            if "rollback_copy_created" in facts or row.size_bytes != 0:
                raise ObjectRestoreError("Recovery journal unexpectedly declares a rollback copy.")
            continue
        copy = facts.get("rollback_copy_created")
        if (copy is None or type(copy.get("size_bytes")) is not int
                or copy["size_bytes"] != row.size_bytes
                or not isinstance(copy.get("metadata"), dict)
                or not isinstance(copy.get("headers"), dict)
                or not isinstance(copy.get("content_type"), str)):
            raise ObjectRestoreError("A recovery copy lacks exact durable creation facts.")
        references.append(ObjectReference(
            bucket_kind=row.bucket_kind, object_key=row.copy_key,
            site=f"backup.RestoreRollbackObject:{row.pk}:copy_key",
            candidate_owner=MAIN_COMPONENT, canonical_makerspace_id=None,
            # This global control model has a coordination maker, not a tenant owner;
            # the scanner derives its module from the model, not row.module_key.
            module_key="",
            coordination_policy="restore_rollback_coordination" if row.makerspace_id else "",
            coordination_makerspace_id=row.makerspace_id,
        ))
        copies.append({
            "bucket_kind": row.bucket_kind, "key": row.copy_key, "size": row.size_bytes,
            "metadata": copy["metadata"], "headers": copy["headers"],
            "content_type": copy["content_type"],
            "makerspace_id": row.makerspace_id, "module_key": row.module_key,
        })
    return tuple(references), copies
