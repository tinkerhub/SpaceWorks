from django.db import connection

from apps.inventory.availability_types import TrackingModeChangeRefused
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode

# Columns only the Availability module writes. Forms and serializers must treat them as
# read-only after creation; quantity changes go through the adjustment/workflow services.
AVAILABILITY_OWNED_FIELDS = (
    "tracking_mode",
    "total_quantity",
    "available_quantity",
    "reserved_quantity",
    "issued_quantity",
    "damaged_quantity",
    "lost_quantity",
    "needs_fix_quantity",
)
_QUANTITY_FIELDS = AVAILABILITY_OWNED_FIELDS[1:]


def change_tracking_mode(product, tracking_mode):
    """The single path for switching a product between quantity and individual tracking.

    The two modes read the same buckets differently (individual buckets are derived from
    asset rows), so a switch is only safe on an empty product: no stock in any bucket,
    no asset rows and no open request holding it. Locks the product row; the caller must
    be inside transaction.atomic(). Returns the locked, updated product.
    """
    if not connection.in_atomic_block:
        raise RuntimeError("change_tracking_mode must be called inside transaction.atomic().")
    if tracking_mode not in TrackingMode.values:
        raise TrackingModeChangeRefused("Invalid tracking mode.")
    locked = InventoryProduct.objects.select_for_update().get(pk=product.pk)
    if locked.tracking_mode == tracking_mode:
        return locked
    blocker = _change_blocker(locked)
    if blocker:
        raise TrackingModeChangeRefused(f"Cannot change tracking mode: {blocker}")
    locked.tracking_mode = tracking_mode
    locked.save(update_fields=["tracking_mode", "updated_at"])
    return locked


def _change_blocker(product):
    from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem

    if any(getattr(product, field) for field in _QUANTITY_FIELDS):
        return "the product still holds stock; bring every quantity to zero first."
    if InventoryAsset.objects.filter(product_id=product.pk).exists():
        return "the product already has unit assets."
    if HardwareRequestItem.objects.filter(
        product_id=product.pk,
        request__status__in=(
            HardwareRequest.Status.ACCEPTED,
            HardwareRequest.Status.ISSUED,
            HardwareRequest.Status.PARTIALLY_RETURNED,
        ),
    ).exists():
        return "the product is on an open request or loan."
    return ""
