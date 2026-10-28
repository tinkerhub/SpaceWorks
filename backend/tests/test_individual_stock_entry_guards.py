"""Individual stock enters through verified units, never typed quantity buckets."""
import pytest

from apps.audit.models import AuditLog
from apps.inventory import availability
from apps.inventory.models import InventoryProduct
from apps.operations.models import InventoryAdjustment
from tests.return_helpers import authenticated_client, make_member, make_product, make_space

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("counts", [
    {"total_quantity": 1, "available_quantity": 0},
    {"total_quantity": 0, "available_quantity": 1},
    {"total_quantity": 2, "available_quantity": 2},
])
def test_individual_create_refuses_nonzero_initial_stock(counts):
    space = make_space("individual-create-refused")
    actor = make_member("individual-create-refused", space)
    before = AuditLog.objects.count()
    response = authenticated_client(actor).post(
        f"/api/v1/admin/makerspace/{space.pk}/inventory",
        {"name": "Tagged meter", "tracking_mode": "individual", **counts}, format="json",
    )
    assert response.status_code == 400
    assert "QR Tools" in str(response.data)
    assert not InventoryProduct.objects.filter(makerspace=space).exists()
    assert not InventoryAdjustment.objects.exists()
    assert AuditLog.objects.count() == before


@pytest.mark.parametrize("mode,total,available", [("individual", 0, 0), ("quantity", 4, 3)])
def test_zero_individual_and_normal_quantity_create(mode, total, available):
    space = make_space("stock-entry-success")
    actor = make_member("stock-entry-success", space)
    response = authenticated_client(actor).post(
        f"/api/v1/admin/makerspace/{space.pk}/inventory",
        {"name": "Meter", "tracking_mode": mode,
         "total_quantity": total, "available_quantity": available}, format="json",
    )
    assert response.status_code == 201, response.data
    product = InventoryProduct.objects.get(makerspace=space, name="Meter")
    assert (product.total_quantity, product.available_quantity) == (total, available)
    assert product.assets.count() == 0


@pytest.mark.parametrize("entry", ["api", "service"])
@pytest.mark.parametrize("deltas", [(1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)])
def test_manual_adjustment_cannot_change_individual_buckets_or_history(entry, deltas):
    space = make_space("individual-adjust")
    actor = make_member("individual-adjust", space)
    product = make_product(space, tracking_mode="individual")
    before = InventoryProduct.objects.filter(pk=product.pk).values().get()
    audit_count = AuditLog.objects.count()
    payload = dict(zip(("delta_available", "delta_damaged", "delta_lost"), deltas))
    payload["reason"] = "Physical recount"
    if entry == "api":
        response = authenticated_client(actor).post(
            f"/api/v1/admin/inventory/{product.pk}/adjust-quantity", payload, format="json",
        )
        assert response.status_code == 400
        if any(deltas):
            assert "QR Tools" in str(response.data)
    else:
        with pytest.raises(availability.InsufficientStock, match="QR Tools"):
            availability.adjust_manual_quantities(product, actor=actor, **payload)
    assert InventoryProduct.objects.filter(pk=product.pk).values().get() == before
    assert not InventoryAdjustment.objects.exists()
    assert AuditLog.objects.count() == audit_count
