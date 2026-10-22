"""F1: asset reconciliation must keep reservations, which never mark asset rows."""
from unittest.mock import Mock

import pytest
from django.db import transaction

from apps.hardware_requests.models import HardwareRequest
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.operations.services_qr_assets import generate_assets_with_qr
from apps.operations.services_transfers import apply_stock_transfer
from tests.test_serialized_handout import (
    authenticated_client,
    issue_request,
    make_accepted_request,
    make_asset,
    make_asset_qr,
    make_issue_evidence,
    make_member,
    make_product,
    make_space,
)

pytestmark = pytest.mark.django_db


def _reserved_individual(slug, units=2, reserve=1):
    makerspace = make_space(slug)
    admin = make_member(f"{slug}-admin", makerspace)
    product = make_product(
        makerspace,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=units,
        available_quantity=units,
    )
    assets = [make_asset(makerspace, product) for _ in range(units)]
    request = make_accepted_request(makerspace, product, reserve, admin)
    return makerspace, admin, product, assets, request


def _buckets(product):
    product.refresh_from_db()
    return (
        product.total_quantity,
        product.available_quantity,
        product.reserved_quantity,
        product.needs_fix_quantity,
    )


def test_reconcile_keeps_unmarked_reservation():
    _ms, _admin, product, _assets, _request = _reserved_individual("recon-keep")

    with transaction.atomic():
        locked = InventoryProduct.objects.select_for_update().get(pk=product.pk)
        availability.reconcile_individual_product_from_assets(locked)

    assert _buckets(product) == (2, 1, 1, 0)


def test_reserve_then_shelve_then_issue_succeeds(monkeypatch):
    makerspace, admin, product, assets, request = _reserved_individual("recon-shelve")
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))

    with transaction.atomic():
        locked = InventoryAsset.objects.select_for_update().get(pk=assets[0].pk)
        availability.move_asset_status(locked, InventoryAsset.Status.MAINTENANCE)
    assert _buckets(product) == (2, 0, 1, 1)

    response = issue_request(
        authenticated_client(admin),
        request,
        make_issue_evidence(makerspace, admin),
        [make_asset_qr(makerspace, assets[1]).payload],
    )

    assert response.status_code == 200, response.data
    request.refresh_from_db()
    assert request.status == HardwareRequest.Status.ISSUED
    product.refresh_from_db()
    assert (product.reserved_quantity, product.issued_quantity) == (0, 1)


def test_reservation_protects_the_last_available_unit():
    _ms, _admin, product, assets, _request = _reserved_individual("recon-last", units=1)

    with pytest.raises(availability.InsufficientStock):
        with transaction.atomic():
            locked = InventoryAsset.objects.select_for_update().get(pk=assets[0].pk)
            availability.move_asset_status(locked, InventoryAsset.Status.MAINTENANCE)

    assert _buckets(product) == (1, 0, 1, 0)


def test_reserve_then_transfer_to_maintenance_keeps_reservation():
    makerspace, admin, product, assets, _request = _reserved_individual("recon-transfer")

    apply_stock_transfer(
        admin,
        makerspace,
        {
            "reason": "Shelve for repair",
            "lines": [{"asset_id": assets[0].id, "to_status": InventoryAsset.Status.MAINTENANCE}],
        },
    )

    assert _buckets(product) == (2, 0, 1, 1)


def test_reserve_then_generate_more_units_then_issue_succeeds(monkeypatch):
    makerspace, admin, product, assets, request = _reserved_individual("recon-generate")
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    qrs = [make_asset_qr(makerspace, asset) for asset in assets]

    generate_assets_with_qr(admin, product, {"count": 2})
    assert _buckets(product) == (4, 3, 1, 0)

    response = issue_request(
        authenticated_client(admin),
        request,
        make_issue_evidence(makerspace, admin),
        [qrs[0].payload],
    )

    assert response.status_code == 200, response.data
    product.refresh_from_db()
    assert (product.available_quantity, product.reserved_quantity, product.issued_quantity) == (3, 0, 1)
