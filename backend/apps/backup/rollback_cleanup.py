"""Actual rollback cleanup owners: host operation lock, then real source fences."""

import logging

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.backup import storage
from apps.backup.models import RestoreRollbackObject
from apps.backup.object_restore_versions import ObjectRestoreError
from apps.backup.operation_lock import OperationLockUnavailable, deployment_operation_lock
from apps.backup.rollback_cleanup_outcomes import RollbackCleanupOutcomeUnavailable, require_cleanup_outcome
from apps.backup.rollback_cleanup_progress import (
    RollbackCleanupProgressUnavailable, read_cleanup_progress, write_cleanup_progress,
)
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace, ModulePurgeReceipt
from apps.makerspaces.module_purge_graph import serialize_binding
from apps.makerspaces.module_purge_receipt_authority import ROLLBACK_FIELDS, validate_receipt
from apps.object_storage import delete_all_versions
from apps.tenant_migration.gate_errors import SourceMigrationGateError
from apps.tenant_migration.gate_locks import unscoped_writer_shared_boundary
from apps.tenant_migration.gate_runtime import fanout_tenant_write
from apps.backup.not_restored import TenantNotRestored


logger = logging.getLogger(__name__)


def _non_atomic():
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ObjectRestoreError("Rollback cleanup requires a non-transactional caller.")


def cleanup_rollback_objects(restore):
    with deployment_operation_lock(blocking=False):
        _non_atomic()
        with unscoped_writer_shared_boundary():
            restore = require_cleanup_outcome(restore.pk)
            return _cleanup_restore(restore)


def _cleanup_restore(restore):
    counts = {"cleaned": 0, "skipped": 0}
    for row in restore.rollback_objects.order_by("pk"):
        if row.makerspace_id is None:
            # The outer unscoped boundary owns these global coordination rows.
            if _frozen(row):
                counts["skipped"] += 1
                continue
            _delete_bytes(row)
            counts["cleaned"] += _settle(row)
            continue
        with fanout_tenant_write(row.makerspace_id, operation="rollback-cleanup", counts=counts) as allowed:
            if not allowed:
                continue
            if _frozen(row):
                counts["skipped"] += 1
                continue
            _delete_bytes(row)
            counts["cleaned"] += _settle(row)
    return {"status": "retained" if counts["skipped"] else "cleaned", **counts}


def cleanup_expired_rollback_objects(limit=100):
    try:
        with deployment_operation_lock(blocking=False):
            _non_atomic()
            if type(limit) is not int or not 1 <= limit <= 1000:
                raise ObjectRestoreError("Rollback cleanup limit is invalid.")
            with unscoped_writer_shared_boundary():
                return _cleanup_expired(limit)
    except OperationLockUnavailable:
        return {"status": "busy", "cleaned": 0, "skipped": 0}


def _expired_candidates(limit, last_id):
    cutoff = timezone.now()
    expired = RestoreRollbackObject.objects.filter(expires_at__lte=cutoff)
    high_water = expired.order_by("-pk").values_list("pk", flat=True).first()
    if high_water is None:
        return []
    expired = expired.filter(pk__lte=high_water)
    rows = list(expired.filter(pk__gt=last_id).order_by("pk")[:limit])
    remaining = limit - len(rows)
    if remaining:
        rows.extend(expired.filter(pk__lte=last_id).order_by("pk")[:remaining])
    return rows


def _cleanup_expired(limit):
    progress = read_cleanup_progress()
    rows = _expired_candidates(limit, progress.last_id)
    counts = {"cleaned": 0, "skipped": 0}
    outcome_refused = False
    for row in rows:
        try:
            require_cleanup_outcome(row.restore_id)
            if row.makerspace_id is None:
                if _frozen(row):
                    counts["skipped"] += 1
                    continue
                _delete_bytes(row)
                counts["cleaned"] += _settle(row)
                continue
            with fanout_tenant_write(row.makerspace_id, operation="rollback-expiry", counts=counts) as allowed:
                if not allowed:
                    continue
                if _frozen(row):
                    counts["skipped"] += 1
                    continue
                _delete_bytes(row)
                counts["cleaned"] += _settle(row)
        except RollbackCleanupOutcomeUnavailable:
            outcome_refused = True
            counts["skipped"] += 1
        except (SourceMigrationGateError, TenantNotRestored, ValidationError):
            counts["skipped"] += 1
        except Exception:
            # Preserve the original row, quota, and locator for another attempt.
            counts["skipped"] += 1
    if rows:
        try:
            # Every examined row advances the scan, including refusals/failures.
            write_cleanup_progress(progress, rows[-1].pk)
        except RollbackCleanupProgressUnavailable:
            error_code = "rollback_cleanup_progress_unconfirmed"
            logger.error(error_code, extra={"error_code": error_code, **counts})
            return {"status": "retained", **counts, "error_code": error_code}
    return {"status": "retained" if outcome_refused else "checked", **counts}


def _binding(row):
    return serialize_binding({name: getattr(row, name) for name in ROLLBACK_FIELDS})


def _frozen(row):
    for receipt in ModulePurgeReceipt.objects.filter(invalidated_at__isnull=True, graph_purged_at__isnull=True).iterator():
        validate_receipt(receipt)
        for binding in receipt.rollback_bindings:
            if binding["id"] == row.pk:
                if binding != _binding(row):
                    raise ObjectRestoreError("A frozen rollback binding changed; cleanup refused.")
                return True
    return False


def _delete_bytes(row):
    from apps.makerspaces.purge_storage import bucket_name

    require_cleanup_outcome(row.restore_id)
    bucket = bucket_name(row.bucket_kind)
    if row.copy_key:
        delete_all_versions(storage.client(), bucket=bucket, key=row.copy_key)
    elif row.source_version_id:
        storage.client().delete_object(Bucket=bucket, Key=row.source_key, VersionId=row.source_version_id)


def _settle(row):
    # Provider I/O above has no SQL transaction. Lock nullable Maker separately;
    # SELECT FOR UPDATE + nullable select_related is rejected by PostgreSQL.
    with transaction.atomic():
        maker = Makerspace.objects.select_for_update().get(pk=row.makerspace_id) if row.makerspace_id else None
        locked = RestoreRollbackObject.objects.select_for_update().filter(pk=row.pk).first()
        if locked is None:
            return 0
        if _binding(locked) != _binding(row) or _frozen(locked):
            raise ObjectRestoreError("Rollback ownership changed before settlement.")
        require_cleanup_outcome(locked.restore_id)
        if maker is not None and locked.size_bytes:
            limits.free_storage(maker, locked.size_bytes)
        locked.delete()
    return 1
