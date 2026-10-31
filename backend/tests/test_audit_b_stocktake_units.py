"""B-F01: individual stocktakes count real units, with four-eyes review."""

import pytest
from rest_framework.exceptions import ValidationError

from apps.inventory.models import InventoryAsset
from apps.operations import services
from apps.operations.models import StocktakeLedgerEntry, StocktakeLine, StocktakeSession
from tests.audit_inventory_helpers import inventory_context, operation_state
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


def _count(ctx, session, **payload):
    return authenticated_client(ctx.counter).post(
        f"/api/v1/admin/stocktakes/{session.pk}/count-lines",
        {"counted_quantity": 1, "condition": "available", **payload}, format="json",
    )


def _review_and_apply(ctx, session):
    counter = authenticated_client(ctx.counter)
    reviewer = authenticated_client(ctx.reviewer)
    base = f"/api/v1/admin/stocktakes/{session.pk}"
    assert counter.post(f"{base}/complete", {}, format="json").status_code == 200
    # Inventory staff count; a distinct Space Manager signs off and applies.
    assert counter.post(f"{base}/approve", {}, format="json").status_code == 403
    assert reviewer.post(f"{base}/approve", {}, format="json").status_code == 200
    applied = reviewer.post(f"{base}/apply-adjustments", {}, format="json")
    assert applied.status_code == 200, applied.data
    session.refresh_from_db()
    assert session.status == StocktakeSession.Status.APPLIED
    assert session.completed_by_id == ctx.counter.pk
    assert session.approved_by_id == ctx.reviewer.pk


def test_individual_product_only_count_refused_without_phantom_stock():
    ctx = inventory_context()
    session = StocktakeSession.objects.create(makerspace=ctx.source, started_by=ctx.counter)
    before = operation_state()

    response = _count(ctx, session, product_id=ctx.individual.pk, counted_quantity=2)

    assert response.status_code == 400, response.data
    assert "product_id" in response.data
    assert operation_state() == before


def test_individual_mixed_product_and_asset_payload_refused_without_mutations():
    ctx = inventory_context()
    session = StocktakeSession.objects.create(makerspace=ctx.source, started_by=ctx.counter)
    before = operation_state()

    response = _count(ctx, session, product_id=ctx.individual.pk, asset_id=ctx.asset.pk, counted_quantity=2)

    assert response.status_code == 400, response.data
    assert operation_state() == before


def test_individual_aggregate_after_asset_count_refused_without_extra_line():
    ctx = inventory_context()
    session = StocktakeSession.objects.create(makerspace=ctx.source, started_by=ctx.counter)
    assert _count(ctx, session, asset_id=ctx.asset.pk).status_code == 201
    before = operation_state()

    response = _count(ctx, session, product_id=ctx.individual.pk, counted_quantity=2)

    assert response.status_code == 400, response.data
    assert operation_state() == before
    assert session.lines.count() == 1
    _review_and_apply(ctx, session)
    ctx.individual.refresh_from_db()
    assert (ctx.individual.available_quantity, ctx.individual.total_quantity) == (1, 1)
    assert ctx.individual.assets.count() == 1


@pytest.mark.parametrize("entrypoint", ["api", "service"])
def test_legacy_individual_aggregate_apply_rolls_back_earlier_quantity_line(entrypoint):
    ctx = inventory_context()
    session = StocktakeSession.objects.create(makerspace=ctx.source, started_by=ctx.counter)
    first = StocktakeLine.objects.create(
        stocktake=session, product=ctx.product, expected_quantity=10,
        counted_quantity=9, variance_quantity=-1,
    )
    legacy = StocktakeLine.objects.create(
        stocktake=session, product=ctx.individual, expected_quantity=1,
        counted_quantity=2, variance_quantity=1,
    )
    assert list(session.lines.values_list("pk", flat=True)) == [first.pk, legacy.pk]
    session = services.complete_stocktake(ctx.counter, session)
    session = services.approve_stocktake(ctx.reviewer, session)
    before = operation_state()

    if entrypoint == "service":
        with pytest.raises(ValidationError):
            services.apply_stocktake_adjustments(ctx.reviewer, session)
    else:
        response = authenticated_client(ctx.reviewer).post(
            f"/api/v1/admin/stocktakes/{session.pk}/apply-adjustments", {}, format="json",
        )
        assert response.status_code == 400, response.data

    assert operation_state() == before
    session.refresh_from_db()
    assert session.status == StocktakeSession.Status.APPROVED
    assert not StocktakeLedgerEntry.objects.filter(stocktake=session).exists()


@pytest.mark.parametrize(
    ("initial_status", "count", "condition", "expected_status", "buckets"),
    [
        ("available", 0, "available", "lost", (0, 0, 1)),
        ("available", 1, "damaged", "damaged", (0, 1, 0)),
        ("lost", 1, "available", "available", (1, 0, 0)),
        ("available", 1, "available", "available", (1, 0, 0)),
    ], ids=["missing-unit", "damaged-unit", "recovered-unit", "present-unit"],
)
def test_real_asset_zero_or_one_count_preserves_unit_backed_stock(
    initial_status, count, condition, expected_status, buckets,
):
    ctx = inventory_context()
    if initial_status == InventoryAsset.Status.LOST:
        ctx.asset.status = initial_status
        ctx.asset.save(update_fields=["status", "updated_at"])
        ctx.individual.available_quantity = 0
        ctx.individual.lost_quantity = 1
        ctx.individual.save(update_fields=["available_quantity", "lost_quantity", "updated_at"])
    session = StocktakeSession.objects.create(makerspace=ctx.source, started_by=ctx.counter)

    response = _count(ctx, session, asset_id=ctx.asset.pk, counted_quantity=count, condition=condition)

    assert response.status_code == 201, response.data
    _review_and_apply(ctx, session)
    ctx.individual.refresh_from_db()
    ctx.asset.refresh_from_db()
    assert ctx.asset.status == expected_status
    assert (ctx.individual.available_quantity, ctx.individual.damaged_quantity, ctx.individual.lost_quantity) == buckets
    assert ctx.individual.total_quantity == ctx.individual.assets.count() == 1


def test_quantity_product_aggregate_count_still_applies_with_distinct_reviewer():
    ctx = inventory_context()
    session = StocktakeSession.objects.create(makerspace=ctx.source, started_by=ctx.counter)

    response = _count(ctx, session, product_id=ctx.product.pk, counted_quantity=8)

    assert response.status_code == 201, response.data
    _review_and_apply(ctx, session)
    ctx.product.refresh_from_db()
    assert (ctx.product.available_quantity, ctx.product.total_quantity) == (8, 8)
    assert list(session.ledger_entries.values_list("product_id", "bucket", "delta")) == [
        (ctx.product.pk, "available", -2),
    ]
