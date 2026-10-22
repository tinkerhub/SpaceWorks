"""M1: the public return path only closes self-checkout loans, and only consistent ones."""
import pytest
from django.db import transaction
from django.test import override_settings

from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem, PublicToolLoan
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, TrackingMode
from tests.test_public_self_checkout import (
    checkout_payload,
    checkout_url,
    eligible_member,
    make_asset_qr,
    make_product,
    make_qr,
    make_space,
    member_client,
    return_payload,
    return_url,
)

pytestmark = pytest.mark.django_db


def _buckets(product):
    product.refresh_from_db()
    return (
        product.available_quantity,
        product.issued_quantity,
        product.needs_fix_quantity,
        product.total_quantity,
    )


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_return_refuses_a_unit_staff_moved_while_it_was_out():
    makerspace = make_space("return-moved-unit")
    product = make_product(
        makerspace,
        public_self_checkout_enabled=True,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=2,
        available_quantity=2,
    )
    assets = [
        InventoryAsset.objects.create(
            makerspace=makerspace, product=product, asset_tag=f"RM-{index}", public_self_checkout_enabled=True
        )
        for index in range(2)
    ]
    qrs = [make_asset_qr(makerspace, asset) for asset in assets]
    borrower = eligible_member(makerspace, "return-moved-a")
    other = eligible_member(makerspace, "return-moved-b")
    for user, qr in ((borrower, qrs[0]), (other, qrs[1])):
        response = member_client(user).post(
            checkout_url(makerspace), checkout_payload(makerspace, user, qr.payload), format="json"
        )
        assert response.status_code == 201
    # Staff pull the first unit onto the fix shelf while it is still recorded as out.
    with transaction.atomic():
        locked = InventoryAsset.objects.select_for_update().get(pk=assets[0].pk)
        availability.move_asset_status(locked, InventoryAsset.Status.MAINTENANCE)
    before = _buckets(product)
    assert before == (0, 1, 1, 2)

    response = member_client(borrower).post(
        return_url(makerspace), return_payload(makerspace, borrower, qrs[0].payload), format="json"
    )

    assert response.status_code == 400
    assert response.data["code"] == "return_validation_error"
    assert _buckets(product) == before
    assets[0].refresh_from_db()
    assert assets[0].status == InventoryAsset.Status.MAINTENANCE
    loan = PublicToolLoan.objects.get(requester=borrower)
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT
    assert loan.return_evidence_id is None


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_return_cannot_close_a_staff_direct_handout():
    makerspace = make_space("return-direct-loan")
    user = eligible_member(makerspace, "return-direct-member")
    product = make_product(makerspace, total_quantity=2, available_quantity=1, issued_quantity=1)
    qr = make_qr(makerspace, product)
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=user,
        requester_username=user.username,
        status=HardwareRequest.Status.ISSUED,
    )
    HardwareRequestItem.objects.create(
        request=request, product=product, requested_quantity=1, accepted_quantity=1, issued_quantity=1
    )
    loan = PublicToolLoan.objects.create(
        makerspace=makerspace,
        qr_code=qr,
        qr_ids=[qr.id],
        request=request,
        requester=user,
        target_type="product",
        target_id=product.id,
        target_label=product.name,
        source=PublicToolLoan.Source.ADMIN_DIRECT,
    )

    response = member_client(user).post(
        return_url(makerspace), return_payload(makerspace, user, qr.payload), format="json"
    )

    assert response.status_code == 409
    loan.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT
    product.refresh_from_db()
    assert (product.available_quantity, product.issued_quantity) == (1, 1)
