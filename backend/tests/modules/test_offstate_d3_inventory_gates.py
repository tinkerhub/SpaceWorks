"""D3 module gates on inventory detail and mutation routes (A1-A4).

Every refusal is asserted together with "nothing changed": a module gate that answers
400 after the write already happened is not a gate. Each OFF case is paired with the
same call succeeding while the module is ON, so the refusal is the module and not some
unrelated validation.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.boxes.models import Box
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import core_module_keys
from apps.operations.models import QrPrintBatch, StocktakeSession, StockTransfer


pytestmark = pytest.mark.django_db

CORE = frozenset(core_module_keys())


def _space(slug, *extra):
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=sorted(CORE | set(extra))
    )


def _client(slug):
    user = User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(user)
    return client


def _module_refusal(response, module):
    assert response.status_code == 400, response.data
    assert module in str(response.data["module"])


@pytest.mark.parametrize("enabled", [False, True])
def test_container_detail_read_and_patch_follow_the_containers_module(enabled):
    space = _space(f"d3-box-{enabled}".lower(), *(["containers"] if enabled else []))
    box = Box.objects.create(makerspace=space, label="Shelf A")
    client = _client(f"d3-box-admin-{enabled}".lower())

    read = client.get(f"/api/v1/admin/containers/{box.pk}")
    patched = client.patch(
        f"/api/v1/admin/containers/{box.pk}", {"label": "Renamed"}, format="json"
    )

    box.refresh_from_db()
    if enabled:
        assert read.status_code == 200, read.data
        assert patched.status_code == 200, patched.data
        assert box.label == "Renamed"
    else:
        _module_refusal(read, "containers")
        _module_refusal(patched, "containers")
        assert box.label == "Shelf A"


def test_container_create_is_refused_without_the_module_and_creates_nothing():
    space = _space("d3-box-create-off")
    client = _client("d3-box-create-admin")

    response = client.post(
        f"/api/v1/admin/makerspace/{space.pk}/containers", {"label": "Bin"}, format="json"
    )

    _module_refusal(response, "containers")
    assert not Box.objects.filter(makerspace=space).exists()


@pytest.mark.parametrize(
    ("module", "url"),
    [
        ("stock_transfers", "/api/v1/admin/stock-transfers/{pk}"),
        ("stocktake", "/api/v1/admin/stocktakes/{pk}"),
        ("qr_print_batches", "/api/v1/admin/qr-print-batches/{pk}"),
    ],
)
@pytest.mark.parametrize("enabled", [False, True])
def test_operations_detail_routes_follow_their_module(module, url, enabled):
    space = _space(f"d3-{module}-{enabled}".replace("_", "-").lower(), *([module] if enabled else []))
    if module == "stock_transfers":
        row = StockTransfer.objects.create(
            makerspace=space, source_makerspace=space, destination_makerspace=space, reason="move"
        )
    elif module == "stocktake":
        row = StocktakeSession.objects.create(makerspace=space)
    else:
        row = QrPrintBatch.objects.create(makerspace=space, title="Labels")

    response = _client(f"d3-{module}-admin-{enabled}".lower()).get(url.format(pk=row.pk))

    if enabled:
        assert response.status_code == 200, response.data
    else:
        _module_refusal(response, module)


def test_cross_space_transfer_refuses_a_destination_without_the_module_and_moves_nothing():
    source = _space("d3-transfer-source", "stock_transfers")
    destination = _space("d3-transfer-destination")
    product = InventoryProduct.objects.create(
        makerspace=source, name="Drill", total_quantity=5, available_quantity=5
    )

    response = _client("d3-transfer-admin").post(
        f"/api/v1/admin/makerspace/{source.pk}/stock-transfers",
        {
            "destination_makerspace_id": destination.pk,
            "reason": "rebalance",
            "lines": [{"product_id": product.pk, "quantity": 2}],
        },
        format="json",
    )

    product.refresh_from_db()
    _module_refusal(response, "stock_transfers")
    assert product.available_quantity == 5
    assert not StockTransfer.objects.exists()
    assert not InventoryProduct.objects.filter(makerspace=destination).exists()


def test_cross_space_transfer_succeeds_when_both_ends_have_the_module():
    source = _space("d3-transfer-source-on", "stock_transfers")
    destination = _space("d3-transfer-destination-on", "stock_transfers")
    product = InventoryProduct.objects.create(
        makerspace=source, name="Drill", total_quantity=5, available_quantity=5
    )

    response = _client("d3-transfer-admin-on").post(
        f"/api/v1/admin/makerspace/{source.pk}/stock-transfers",
        {
            "destination_makerspace_id": destination.pk,
            "reason": "rebalance",
            "lines": [{"product_id": product.pk, "quantity": 2}],
        },
        format="json",
    )

    product.refresh_from_db()
    assert response.status_code == 201, response.data
    assert product.available_quantity == 3


def _unit(space):
    product = InventoryProduct.objects.create(
        makerspace=space,
        name="Multimeter",
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    asset = InventoryAsset.objects.create(makerspace=space, product=product, asset_tag="MM-1")
    return product, asset


@pytest.mark.parametrize("enabled", [False, True])
def test_asset_routes_follow_the_asset_units_module(enabled):
    space = _space(f"d3-assets-{enabled}".lower(), *(["asset_units"] if enabled else []))
    product, asset = _unit(space)
    client = _client(f"d3-assets-admin-{enabled}".lower())

    listed = client.get(f"/api/v1/admin/inventory/{product.pk}/assets")
    history = client.get(f"/api/v1/admin/assets/{asset.pk}/qr-history")
    edited = client.patch(
        f"/api/v1/admin/assets/{asset.pk}", {"serial_number": "SN-9"}, format="json"
    )
    shelved = client.post(
        f"/api/v1/admin/assets/{asset.pk}/fix-status", {"action": "shelve"}, format="json"
    )

    asset.refresh_from_db()
    if enabled:
        for response in (listed, history, edited, shelved):
            assert response.status_code == 200, response.data
        assert asset.serial_number == "SN-9"
        assert asset.status == InventoryAsset.Status.MAINTENANCE
    else:
        for response in (listed, history, edited, shelved):
            _module_refusal(response, "asset_units")
        assert asset.serial_number == ""
        assert asset.status == InventoryAsset.Status.AVAILABLE
