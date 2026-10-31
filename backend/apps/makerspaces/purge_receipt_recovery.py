"""Restore barrier: missing receipt schema fails readiness closed."""

import logging

from django.utils import timezone

from .models import ModulePurgeReceipt, PurgeReceipt

logger = logging.getLogger(__name__)


def invalidate_restored_receipts(*, using="default"):
    rows = PurgeReceipt.objects.using(using)
    count = rows.filter(invalidated_at__isnull=True).update(invalidated_at=timezone.now())
    module_rows = ModulePurgeReceipt.objects.using(using)
    count += module_rows.filter(invalidated_at__isnull=True).update(
        invalidated_at=timezone.now(), invalidation_reason="recovery",
    )
    if (rows.filter(invalidated_at__isnull=True).exists()
            or module_rows.filter(invalidated_at__isnull=True).exists()):
        raise RuntimeError("Restored purge receipts remain active; recovery readiness is refused.")
    logger.info("restored_purge_receipts_invalidated", extra={"receipt_count": count, "database_alias": using})
    return count
