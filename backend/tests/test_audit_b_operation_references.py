"""B-F02: submitted references fail with scoped 404s and atomic rollback."""

import pytest

from apps.operations.models import StocktakeSession
from tests.audit_inventory_helpers import (
    assert_not_found, inventory_context, operation_state,
)
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db
MISSING_ID = 2_000_000_000


@pytest.mark.parametrize("reference", ["intra-product", "intra-asset", "cross-product"])
@pytest.mark.parametrize("identity", ["missing", "foreign"])
def test_transfer_invalid_item_reference_is_typed_404_without_mutations(reference, identity):
    ctx = inventory_context()
    asset = reference == "intra-asset"
    foreign = ctx.foreign_asset if asset else ctx.foreign_product
    payload = {
        "reason": "Verify submitted reference",
        "lines": [{"asset_id" if asset else "product_id": MISSING_ID if identity == "missing" else foreign.pk}],
    }
    if reference == "cross-product":
        payload["destination_makerspace_id"] = ctx.destination.pk
    before = operation_state()

    response = ctx.client.post(
        f"/api/v1/admin/makerspace/{ctx.source.pk}/stock-transfers", payload, format="json",
    )

    assert_not_found(response)
    assert operation_state() == before


@pytest.mark.parametrize("cross_space", [False, True], ids=["intra", "cross"])
@pytest.mark.parametrize("field", ["source_container_id", "destination_container_id"])
@pytest.mark.parametrize("identity", ["missing", "foreign"])
def test_transfer_invalid_container_is_typed_404_without_mutations(cross_space, field, identity):
    ctx = inventory_context()
    payload = {
        "reason": "Verify container reference",
        "lines": [{"product_id": ctx.product.pk, "quantity": 2}],
        field: MISSING_ID if identity == "missing" else ctx.foreign_box.pk,
    }
    if cross_space:
        payload["destination_makerspace_id"] = ctx.destination.pk
    before = operation_state()

    response = ctx.client.post(
        f"/api/v1/admin/makerspace/{ctx.source.pk}/stock-transfers", payload, format="json",
    )

    assert_not_found(response)
    assert operation_state() == before


@pytest.mark.parametrize("reference", ["intra-product", "intra-asset", "cross-product"])
@pytest.mark.parametrize("identity", ["missing", "foreign"])
def test_transfer_later_invalid_line_rolls_back_first_valid_line(reference, identity):
    ctx = inventory_context()
    asset = reference == "intra-asset"
    foreign = ctx.foreign_asset if asset else ctx.foreign_product
    payload = {
        "reason": "Rollback an earlier quantity split or destination credit",
        "destination_container_id": ctx.source_box.pk,
        "lines": [
            {"product_id": ctx.product.pk, "quantity": 2},
            {"asset_id" if asset else "product_id": MISSING_ID if identity == "missing" else foreign.pk},
        ],
    }
    if reference == "cross-product":
        payload.update(
            destination_makerspace_id=ctx.destination.pk,
            destination_container_id=ctx.destination_box.pk,
        )
    before = operation_state()

    response = ctx.client.post(
        f"/api/v1/admin/makerspace/{ctx.source.pk}/stock-transfers", payload, format="json",
    )

    assert_not_found(response)
    assert operation_state() == before


@pytest.mark.parametrize("identity", ["missing", "foreign"])
def test_stocktake_create_invalid_container_is_typed_404_without_mutations(identity):
    ctx = inventory_context()
    before = operation_state()

    response = authenticated_client(ctx.counter).post(
        f"/api/v1/admin/makerspace/{ctx.source.pk}/stocktakes",
        {"container_id": MISSING_ID if identity == "missing" else ctx.foreign_box.pk}, format="json",
    )

    assert_not_found(response)
    assert operation_state() == before


@pytest.mark.parametrize("field", ["product_id", "asset_id", "container_id"])
@pytest.mark.parametrize("identity", ["missing", "foreign"])
def test_stocktake_count_invalid_reference_is_typed_404_without_mutations(field, identity):
    ctx = inventory_context()
    session = StocktakeSession.objects.create(makerspace=ctx.source, started_by=ctx.counter)
    foreign = {"product_id": ctx.foreign_product, "asset_id": ctx.foreign_asset, "container_id": ctx.foreign_box}
    payload = {"counted_quantity": 1, field: MISSING_ID if identity == "missing" else foreign[field].pk}
    if field == "container_id":
        payload["product_id"] = ctx.product.pk
    before = operation_state()

    response = authenticated_client(ctx.counter).post(
        f"/api/v1/admin/stocktakes/{session.pk}/count-lines", payload, format="json",
    )

    assert_not_found(response)
    assert operation_state() == before
