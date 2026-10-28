"""Approval explains missing unit registration without suggesting phantom stock."""
import pytest
from django.db import transaction

from apps.audit.models import AuditLog
from apps.hardware_requests.models import HardwareRequest
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.operations.services_qr_assets import generate_assets_with_qr
from tests.return_helpers import authenticated_client, make_member, make_product, make_space
from tests.test_partial_accept import accept_url, make_request
from tests.test_serialized_handout import make_asset

pytestmark = pytest.mark.django_db


def test_missing_units_error_then_verified_generation_allows_approval_and_preserves_reservations():
    space = make_space("approval-register-units")
    actor = make_member("approval-register-units", space)
    product = make_product(space, name="Tagged meter", tracking_mode="individual",
                           total_quantity=0, available_quantity=0)
    request = make_request(space, [(product, 1)])
    client = authenticated_client(actor)
    before = AuditLog.objects.count()
    response = client.post(accept_url(request), {}, format="json")
    assert response.status_code == 409
    assert response.data["code"] == "insufficient_stock"
    message = str(response.data)
    assert product.name in message
    assert "No individual units are registered" in message
    assert "Verify physical stock" in message and "QR Tools" in message
    request.refresh_from_db()
    product.refresh_from_db()
    assert request.status == HardwareRequest.Status.PENDING_APPROVAL
    assert request.items.get().accepted_quantity == 0
    assert (product.total_quantity, product.available_quantity, product.reserved_quantity) == (0, 0, 0)
    assert AuditLog.objects.count() == before

    generate_assets_with_qr(actor, product, {"count": 2})
    accepted = client.post(accept_url(request), {}, format="json")
    assert accepted.status_code == 200, accepted.data
    request.refresh_from_db()
    assert request.status == HardwareRequest.Status.ACCEPTED
    generate_assets_with_qr(actor, product, {"count": 1})
    with transaction.atomic():
        locked = InventoryProduct.objects.select_for_update().get(pk=product.pk)
        availability.reconcile_individual_product_from_assets(locked)
    product.refresh_from_db()
    assert (product.total_quantity, product.available_quantity, product.reserved_quantity) == (3, 2, 1)


@pytest.mark.parametrize("status", [InventoryAsset.Status.ISSUED, InventoryAsset.Status.MAINTENANCE])
def test_existing_unavailable_units_do_not_recommend_generating_replacements(status):
    space = make_space("approval-unavailable-units")
    actor = make_member("approval-unavailable-units", space)
    product = make_product(space, tracking_mode="individual", total_quantity=1, available_quantity=0,
                           issued_quantity=int(status == InventoryAsset.Status.ISSUED),
                           needs_fix_quantity=int(status == InventoryAsset.Status.MAINTENANCE))
    make_asset(space, product, status=status)
    request = make_request(space, [(product, 1)])
    response = authenticated_client(actor).post(accept_url(request), {}, format="json")
    assert response.status_code == 409
    assert response.data["code"] == "insufficient_stock"
    message = str(response.data).lower()
    assert "check unit statuses and reservations" in message
    assert "generate" not in message
    request.refresh_from_db()
    product.refresh_from_db()
    assert request.status == HardwareRequest.Status.PENDING_APPROVAL
    assert product.reserved_quantity == 0
