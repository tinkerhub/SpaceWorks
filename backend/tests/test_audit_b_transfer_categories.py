"""B-F03: destination category identity is local, deterministic and private."""

import pytest

from apps.inventory.models import Category, InventoryAsset, InventoryProduct, TrackingMode
from tests.audit_inventory_helpers import inventory_context, operation_state
from tests.return_helpers import make_product

pytestmark = pytest.mark.django_db


def _category(space, slug="mcu"):
    return Category.objects.create(makerspace=space, name=slug.upper(), slug=slug)


def _transfer(ctx, quantity):
    return ctx.client.post(
        f"/api/v1/admin/makerspace/{ctx.source.pk}/stock-transfers",
        {
            "destination_makerspace_id": ctx.destination.pk,
            "destination_container_id": ctx.destination_box.pk,
            "reason": "Top up partner inventory",
            "lines": [{"product_id": ctx.product.pk, "quantity": quantity}],
        }, format="json",
    )


def _category_identities():
    return list(Category.objects.order_by("pk").values_list("pk", "makerspace_id", "slug", "name"))


@pytest.mark.parametrize("existing", [False, True], ids=["create", "topup"])
def test_cross_space_slug_counterpart_uses_destination_category_and_reuses_product(existing):
    ctx = inventory_context()
    source_category = _category(ctx.source)
    destination_category = _category(ctx.destination)
    assert source_category.pk != destination_category.pk
    ctx.product.category = source_category
    ctx.product.save(update_fields=["category", "updated_at"])
    if existing:
        expected = make_product(
            ctx.destination, name=ctx.product.name.lower(), category=destination_category,
            box=ctx.destination_box, total_quantity=2, available_quantity=2, is_public=False,
        )
    categories_before = _category_identities()

    first = _transfer(ctx, 2)
    assert first.status_code == 201, first.data
    received = InventoryProduct.objects.get(makerspace=ctx.destination, category=destination_category)
    assert received.box_id == ctx.destination_box.pk
    assert received.is_public is False
    if existing:
        assert received.pk == expected.pk
    second = _transfer(ctx, 3)

    assert second.status_code == 201, second.data
    received.refresh_from_db()
    ctx.product.refresh_from_db()
    assert (received.available_quantity, received.total_quantity) == ((7, 7) if existing else (5, 5))
    assert received.is_public is False
    assert (ctx.product.available_quantity, ctx.product.total_quantity) == (5, 5)
    assert InventoryProduct.objects.filter(makerspace=ctx.destination).count() == 1
    assert _category_identities() == categories_before


@pytest.mark.parametrize("source_has_category", [False, True], ids=["null-source", "no-counterpart"])
@pytest.mark.parametrize("existing", [False, True], ids=["create", "topup"])
def test_cross_space_without_counterpart_reuses_uncategorized_stock_without_creating_category(
    source_has_category, existing,
):
    ctx = inventory_context()
    if source_has_category:
        ctx.product.category = _category(ctx.source)
        ctx.product.save(update_fields=["category", "updated_at"])
    # Same name/container in another local category must remain a separate row.
    decoy = make_product(
        ctx.destination, name=ctx.product.name, category=_category(ctx.destination, "tools"),
        box=ctx.destination_box, total_quantity=4, available_quantity=4, is_public=False,
    )
    if existing:
        expected = make_product(
            ctx.destination, name=ctx.product.name, category=None,
            box=ctx.destination_box, total_quantity=2, available_quantity=2, is_public=False,
        )
    categories_before = _category_identities()

    first = _transfer(ctx, 2)
    assert first.status_code == 201, first.data
    received = InventoryProduct.objects.get(makerspace=ctx.destination, category__isnull=True)
    if existing:
        assert received.pk == expected.pk
    second = _transfer(ctx, 3)

    assert second.status_code == 201, second.data
    received.refresh_from_db()
    decoy.refresh_from_db()
    ctx.product.refresh_from_db()
    assert (received.available_quantity, received.total_quantity) == ((7, 7) if existing else (5, 5))
    assert received.box_id == ctx.destination_box.pk
    assert received.is_public is False
    assert (decoy.available_quantity, decoy.total_quantity) == (4, 4)
    assert (ctx.product.available_quantity, ctx.product.total_quantity) == (5, 5)
    assert InventoryProduct.objects.filter(makerspace=ctx.destination).count() == 2
    assert _category_identities() == categories_before


def test_cross_space_different_local_category_does_not_merge_with_slug_counterpart():
    ctx = inventory_context()
    ctx.product.category = _category(ctx.source)
    ctx.product.save(update_fields=["category", "updated_at"])
    counterpart = _category(ctx.destination)
    decoy = make_product(
        ctx.destination, name=ctx.product.name, category=_category(ctx.destination, "tools"),
        box=ctx.destination_box, total_quantity=4, available_quantity=4,
    )
    categories_before = _category_identities()

    for quantity in (2, 3):
        response = _transfer(ctx, quantity)
        assert response.status_code == 201, response.data

    received = InventoryProduct.objects.get(makerspace=ctx.destination, category=counterpart)
    decoy.refresh_from_db()
    assert (received.available_quantity, received.total_quantity) == (5, 5)
    assert received.is_public is False
    assert (decoy.available_quantity, decoy.total_quantity) == (4, 4)
    assert InventoryProduct.objects.filter(makerspace=ctx.destination).count() == 2
    assert _category_identities() == categories_before


def test_cross_space_individual_destination_slug_counterpart_refused_atomically():
    ctx = inventory_context()
    ctx.product.category = _category(ctx.source)
    ctx.product.save(update_fields=["category", "updated_at"])
    counterpart = _category(ctx.destination)
    destination = make_product(
        ctx.destination, name=ctx.product.name, category=counterpart, box=ctx.destination_box,
        tracking_mode=TrackingMode.INDIVIDUAL, total_quantity=1, available_quantity=1,
    )
    InventoryAsset.objects.create(makerspace=ctx.destination, product=destination, asset_tag="PARTNER-1")
    before = operation_state()
    categories_before = _category_identities()

    response = _transfer(ctx, 2)

    assert response.status_code == 400, response.data
    assert operation_state() == before
    assert _category_identities() == categories_before
