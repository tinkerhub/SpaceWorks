"""B-F02/B-F04: unit generation respects retained batch scope and module state."""

import pytest
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.boxes.models import QrCode
from apps.inventory.models import InventoryProduct, TrackingMode
from apps.operations import services
from apps.operations.models import QrPrintBatch
from tests.audit_inventory_helpers import assert_not_found, inventory_context, operation_state
from tests.return_helpers import make_product

pytestmark = pytest.mark.django_db


def _generate(ctx, product, **options):
    return ctx.client.post(
        f"/api/v1/admin/products/{product.pk}/assets/generate",
        {"count": 2, **options}, format="json",
    )


@pytest.mark.parametrize("entrypoint", ["api", "service"])
@pytest.mark.parametrize("batch_option", ["existing", "create"])
def test_batched_unit_generation_with_print_module_off_has_no_side_effects(entrypoint, batch_option):
    ctx = inventory_context()
    retained = QrPrintBatch.objects.create(makerspace=ctx.source, title="Retained labels", created_by=ctx.actor)
    ctx.source.enabled_modules = [key for key in ctx.source.enabled_modules if key != "qr_print_batches"]
    ctx.source.save(update_fields=["enabled_modules", "updated_at"])
    # Empty quantity stock would be converted by the generation service; refusal must
    # also leave tracking_mode unchanged, not just avoid newly inserted units.
    product = make_product(ctx.source, name="Empty drill", total_quantity=0, available_quantity=0)
    options = {"print_batch_id": retained.pk} if batch_option == "existing" else {"create_print_batch": True}
    before = operation_state()

    if entrypoint == "service":
        with pytest.raises(ValidationError) as error:
            services.generate_assets_with_qr(ctx.actor, product, {"count": 2, **options})
        assert "qr_print_batches" in str(error.value.detail["module"])
    else:
        response = _generate(ctx, product, **options)
        assert response.status_code == 400, response.data
        assert "qr_print_batches" in str(response.data["module"])

    assert operation_state() == before


def test_unbatched_unit_generation_succeeds_with_only_asset_units_capability():
    ctx = inventory_context()
    ctx.source.enabled_modules = [key for key in ctx.source.enabled_modules if key != "qr_print_batches"]
    ctx.source.save(update_fields=["enabled_modules", "updated_at"])
    product = make_product(
        ctx.source, name="Unbatched drill", tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=0, available_quantity=0,
    )

    response = _generate(ctx, product)

    assert response.status_code == 201, response.data
    assert response.data["print_batch_id"] is None
    assert len(response.data["assets"]) == 2
    product.refresh_from_db()
    assert product.assets.count() == product.available_quantity == product.total_quantity == 2
    assert QrCode.objects.filter(makerspace=ctx.source, target_type="asset", target_id__in=product.assets.values("pk")).count() == 2
    assert not QrPrintBatch.objects.exists()
    assert AuditLog.objects.filter(action="asset_units.generated", target_id=str(product.pk)).count() == 1


@pytest.mark.parametrize("identity", ["missing", "foreign"])
def test_generate_invalid_batch_is_typed_404_and_rolls_back_tracking_conversion(identity):
    ctx = inventory_context()
    foreign = QrPrintBatch.objects.create(makerspace=ctx.foreign, title="Foreign labels")
    product = make_product(ctx.source, name="Empty drill", total_quantity=0, available_quantity=0)
    before = operation_state()

    response = _generate(ctx, product, print_batch_id=2_000_000_000 if identity == "missing" else foreign.pk)

    assert_not_found(response)
    assert operation_state() == before


def test_generate_valid_existing_batch_preserves_existing_items_and_appends_units():
    ctx = inventory_context()
    product = make_product(
        ctx.source, name="Batched drill", tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=0, available_quantity=0,
    )
    batch = QrPrintBatch.objects.create(makerspace=ctx.source, title="Existing labels", created_by=ctx.actor)
    first = _generate(ctx, product, print_batch_id=batch.pk)
    assert first.status_code == 201, first.data
    first_items = list(batch.items.order_by("pk").values())

    second = _generate(ctx, product, print_batch_id=batch.pk)

    assert second.status_code == 201, second.data
    assert first.data["print_batch_id"] == second.data["print_batch_id"] == batch.pk
    assert QrPrintBatch.objects.count() == 1
    assert list(batch.items.order_by("pk").values())[:2] == first_items
    assert batch.items.count() == product.assets.count() == 4
    product.refresh_from_db()
    assert product.available_quantity == product.total_quantity == 4
    assert set(batch.items.values_list("target_id", flat=True)) == set(product.assets.values_list("pk", flat=True))
    assert not InventoryProduct.objects.filter(pk=product.pk).exclude(tracking_mode=TrackingMode.INDIVIDUAL).exists()
