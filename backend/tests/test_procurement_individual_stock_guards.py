"""A received procurement item cannot mint or top up serialized stock."""
import pytest
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.inventory.models import InventoryProduct
from apps.operations.models import InventoryAdjustment
from apps.procurement.services import move_to_inventory
from tests.test_procurement_move_to_inventory import (
    authenticated_client, create_payload, make_inventory_manager, make_space,
    move_inventory_url, product, received_item,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("mode", ["create", "topup"])
@pytest.mark.parametrize("entry", ["api", "service"])
def test_individual_procurement_refusal_is_atomic(mode, entry):
    space = make_space("procurement-individual")
    actor = make_inventory_manager("procurement-individual", space)
    item = received_item(space)
    existing = product(space, tracking_mode="individual")
    before_product = InventoryProduct.objects.filter(pk=existing.pk).values().get()
    before_item = type(item).objects.filter(pk=item.pk).values().get()
    audit_count = AuditLog.objects.count()
    payload = create_payload(tracking_mode="individual") if mode == "create" else {
        "mode": "topup", "product_id": existing.pk, "quantity": 3,
    }
    if entry == "api":
        response = authenticated_client(actor).post(move_inventory_url(item), payload, format="json")
        assert response.status_code == 400
        assert "QR Tools" in str(response.data)
    else:
        args = {**create_payload(), **payload}
        with pytest.raises(ValidationError, match="QR Tools"):
            move_to_inventory(actor, item, **args)
    assert type(item).objects.filter(pk=item.pk).values().get() == before_item
    assert InventoryProduct.objects.filter(pk=existing.pk).values().get() == before_product
    assert InventoryProduct.objects.filter(makerspace=space).count() == 1
    assert not InventoryAdjustment.objects.exists()
    assert AuditLog.objects.count() == audit_count
