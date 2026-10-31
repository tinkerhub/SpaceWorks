"""Conservative release of accepted, unissued request reservations."""

from collections import Counter

from django.db import connection
from django.db.models import Count, Sum

from apps.inventory.availability_types import InsufficientStock
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode


def release_request_reservation(request):
    """Release only this request's demand after proving the entire pooled balance.

    The caller holds the request lock and has checked that nothing was issued.
    Other request rows are READ, never locked after products: every normal accept,
    issue and cancellation serializes its stock writes through these product locks.
    No asset locks are acquired here (handover locks assets before products).
    """
    from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem

    if not connection.in_atomic_block:
        raise RuntimeError("release_request_reservation requires transaction.atomic().")
    if request.status != HardwareRequest.Status.ACCEPTED:
        raise InsufficientStock("Only accepted request reservations can be released.")

    quantities = Counter()
    for item in request.items.all():
        quantities[item.product_id] += item.accepted_quantity
    products = list(
        InventoryProduct.objects.select_for_update()
        .filter(pk__in=quantities).order_by("pk")
    )
    if len(products) != len(quantities) or not any(quantities.values()):
        raise InsufficientStock("Accepted reservation has no attributable stock.")

    # Validate every accepted request/product binding, even zero-quantity lines.
    demand = Counter()
    rows = (
        HardwareRequestItem.objects.filter(
            product_id__in=quantities,
            request__status=HardwareRequest.Status.ACCEPTED,
        )
        .values("product_id", "request__makerspace_id")
        .annotate(quantity=Sum("accepted_quantity"))
    )
    for row in rows:
        if row["request__makerspace_id"] != request.makerspace_id:
            raise InsufficientStock("Accepted stock has a foreign makerspace binding.")
        demand[row["product_id"]] += row["quantity"]

    # Read physical reservations independently of the accepted request ledger.
    physical = {}
    for row in (
        InventoryAsset.objects.filter(product_id__in=quantities)
        .values("product_id", "makerspace_id", "status").annotate(quantity=Count("pk"))
    ):
        if row["makerspace_id"] != request.makerspace_id:
            raise InsufficientStock("Asset stock has a foreign makerspace binding.")
        physical.setdefault(row["product_id"], Counter())[row["status"]] += row["quantity"]

    # Check ALL products before the first counter write. Ambiguity is a refusal,
    # never an invitation to repair buckets or consume another request's stock.
    for product in products:
        if product.makerspace_id != request.makerspace_id:
            raise InsufficientStock("Product belongs to another makerspace.")
        assets = physical.get(product.pk, Counter())
        if product.tracking_mode == TrackingMode.QUANTITY:
            if assets:
                raise InsufficientStock("Quantity-tracked stock has ambiguous asset backing.")
        elif product.tracking_mode == TrackingMode.INDIVIDUAL:
            available = assets[InventoryAsset.Status.AVAILABLE]
            if available < demand[product.pk] or product.available_quantity != available - demand[product.pk]:
                raise InsufficientStock("Individual available stock does not match accepted demand.")
        else:
            raise InsufficientStock("Unknown stock tracking mode.")
        expected = demand[product.pk] + assets[InventoryAsset.Status.RESERVED]
        if product.reserved_quantity != expected or demand[product.pk] < quantities[product.pk]:
            raise InsufficientStock("Reserved stock does not exactly match attributable demand.")

    for product in products:
        quantity = quantities[product.pk]
        if quantity:
            product.reserved_quantity -= quantity
            product.available_quantity += quantity
            product.save(update_fields=["reserved_quantity", "available_quantity", "updated_at"])
