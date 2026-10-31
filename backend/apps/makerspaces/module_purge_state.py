"""Persistent intent barriers and current source/incarnation checks."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Makerspace, ModulePurgeReceipt
from .module_purge_receipt_authority import bounded_id, validate_receipt
from .purge_intent import storage_origins
from .purge_locks import assert_recovery_allowed


def assert_no_inprogress(makerspace_ids=None):
    query = ModulePurgeReceipt.objects.filter(invalidated_at__isnull=True, graph_purged_at__isnull=True)
    if makerspace_ids is not None:
        query = query.filter(source_makerspace_id__in=makerspace_ids)
    if query.exists():
        raise ValidationError("An unfinished module purge intent prevents capture or storage reconciliation.")


def require_source(space):
    from apps.tenant_migration.models_source_gate import SourceMigrationGate
    from apps.tenant_migration.models import TenantImportJob

    if (space.purge_started_at is not None
            or space.lifecycle_state != Makerspace.LifecycleState.ACTIVE
            or SourceMigrationGate.objects.filter(makerspace_id=space.pk).exclude(
                state=SourceMigrationGate.State.OPEN,
            ).exists()
            or TenantImportJob.objects.exclude(status__in=TenantImportJob.TERMINAL_STATUSES).exists()):
        raise ValidationError("The current source or tenant lifecycle refuses module cleanup.")


def current_authority(receipt, *, space=None):
    validate_receipt(receipt)
    state = assert_recovery_allowed(receipt.source_makerspace_id)
    if receipt.invalidated_at is not None or receipt.auth_generation != state.auth_generation:
        raise ValidationError("Module cleanup authority was invalidated or belongs to another root generation.")
    if receipt.storage_origins != storage_origins():
        raise ValidationError("Module cleanup physical storage origins changed.")
    if space is None:
        space = Makerspace._base_manager.get(pk=receipt.source_makerspace_id)
    if (space.pk != receipt.source_makerspace_id or space.public_code != receipt.source_public_code
            or space.created_at != receipt.source_created_at or receipt.module_key in (space.enabled_modules or [])):
        raise ValidationError("Module cleanup tenant incarnation or installation state changed.")
    require_source(space)
    return space


def enabling_modules(space, modules):
    # Caller owns the real source boundary BEFORE the Maker row lock. The SQL
    # trigger also enforces this for raw ORM updates, in the same transaction.
    added = set(modules) - set(space.enabled_modules or [])
    rows = ModulePurgeReceipt.objects.select_for_update().filter(
        source_makerspace_id=space.pk, module_key__in=added, invalidated_at__isnull=True,
    )
    if rows.filter(graph_purged_at__isnull=True).exists():
        raise ValidationError("Finish the module purge intent before reinstalling this module.")
    rows.update(invalidated_at=timezone.now(), invalidation_reason="module_enabled")


def validate_maker_id(value):
    if not bounded_id(value, 2147483647):
        raise ValidationError("Module cleanup requires a bounded makerspace ID.")
