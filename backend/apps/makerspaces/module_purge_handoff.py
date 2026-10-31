"""Transfer valid module closure to whole-tenant authority while Maker still exists."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import ModulePurgeReceipt
from .module_purge_namespaces import enumerate_closure
from .module_purge_receipt_authority import validate_receipt
from .purge_intent import storage_origins
from .purge_locks import assert_recovery_allowed


def _compatible(receipt, space):
    validate_receipt(receipt)
    state = assert_recovery_allowed(space.pk)
    if (receipt.invalidated_at is not None or receipt.auth_generation != state.auth_generation
            or receipt.source_makerspace_id != space.pk
            or receipt.source_public_code != space.public_code or receipt.source_created_at != space.created_at
            or receipt.storage_origins != storage_origins()
            or receipt.module_key in (space.enabled_modules or [])):
        raise ValidationError("Incompatible retained module authority prevents tenant purge handoff.")


def collect_handoff(space, s3, verify):
    receipts = list(ModulePurgeReceipt.objects.filter(
        source_makerspace_id=space.pk, invalidated_at__isnull=True,
    ).order_by("pk"))
    closure = set()
    for receipt in receipts:
        _compatible(receipt, space)
        closure.update(enumerate_closure(receipt, s3, verify))
    return receipts, closure


def invalidate_handoff(space, receipts):
    rows = list(ModulePurgeReceipt.objects.select_for_update().filter(
        source_makerspace_id=space.pk, invalidated_at__isnull=True,
    ).order_by("pk"))
    if [row.pk for row in rows] != [row.pk for row in receipts]:
        raise ValidationError("Module cleanup handoff inventory changed.")
    for row in rows:
        _compatible(row, space)
        row.invalidated_at = timezone.now()
        row.invalidation_reason = "tenant_purged"
        row.save(update_fields=["invalidated_at", "invalidation_reason"])
