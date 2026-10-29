"""Manual counts are for quantity products; unit-backed workflows keep their primitive."""
from django.db import transaction

from apps.inventory.availability_quantities import adjust_quantities
from apps.inventory.availability_types import InsufficientStock
from apps.inventory.models import InventoryProduct, TrackingMode


@transaction.atomic
def adjust_manual_quantities(product, **kwargs):
    locked = InventoryProduct.objects.select_for_update().get(pk=product.pk)
    if locked.tracking_mode == TrackingMode.INDIVIDUAL:
        raise InsufficientStock(
            "Individual stock is derived from unit assets. Verify physical units and use QR Tools "
            "to generate units or update their status; manual quantity adjustments are unavailable."
        )
    return adjust_quantities(locked, **kwargs)
