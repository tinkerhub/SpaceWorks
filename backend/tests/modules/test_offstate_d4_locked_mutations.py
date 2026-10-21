"""Locked module re-checks on the remaining inventory mutations (containers, QR print
batches, stocktake, asset units).

The view-boundary `require_module` reads an unlocked makerspace row, so an uninstall
can commit between that check and the write. Each test removes the view check (the
monkeypatch IS that race window) and proves the write itself still refuses under the
makerspace lock and leaves nothing behind -- and, with the module on, that the same
call succeeds, so the refusal is the module and not some unrelated validation.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import Box, QrCode
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import core_module_keys
from apps.operations import views_containers, views_qr_batches, views_stocktake
from apps.operations.models import QrPrintBatch, QrPrintBatchItem, StocktakeLine, StocktakeSession


pytestmark = pytest.mark.django_db

CORE = frozenset(core_module_keys())


@pytest.fixture
def raced(monkeypatch):
    """Skip every view-boundary module check, as if the uninstall landed just after it."""
    for module in (views_containers, views_qr_batches, views_stocktake):
        monkeypatch.setattr(module, "require_module", lambda *args, **kwargs: None)


def _setup(tag, module, enabled):
    space = Makerspace.objects.create(
        name=tag, slug=tag, enabled_modules=sorted(CORE | ({module} if enabled else set()))
    )
    user = User.objects.create_user(
        username=tag, email=f"{tag}@example.test", role=User.Role.SUPERADMIN,
        is_staff=True, is_superuser=True, access_status=User.AccessStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(user)
    return space, client


def _outcome(response, module, enabled, ok=(200, 201)):
    if enabled:
        assert response.status_code in ok, response.data
    else:
        assert response.status_code == 400, response.data
        assert module in str(response.data["module"])


@pytest.mark.parametrize("enabled", [False, True])
def test_container_move_rechecks_containers_under_the_lock(raced, enabled):
    space, client = _setup(f"d4-move-{enabled}".lower(), "containers", enabled)
    box = Box.objects.create(makerspace=space, label="Shelf A")

    response = client.post(f"/api/v1/admin/containers/{box.pk}/move", {"label": "Moved"}, format="json")

    box.refresh_from_db()
    _outcome(response, "containers", enabled)
    assert box.label == ("Moved" if enabled else "Shelf A")
    assert AuditLog.objects.filter(action="container.moved").exists() is enabled


@pytest.mark.parametrize("enabled", [False, True])
def test_qr_batch_create_and_item_add_recheck_the_module_under_the_lock(raced, enabled):
    space, client = _setup(f"d4-batch-{enabled}".lower(), "qr_print_batches", enabled)
    product = InventoryProduct.objects.create(makerspace=space, name="Drill", total_quantity=1, available_quantity=1)
    qr = QrCode.objects.create(makerspace=space, target_type=QrCode.TargetType.PRODUCT, target_id=product.pk)
    batch = QrPrintBatch.objects.create(makerspace=space, title="Existing")

    created = client.post(f"/api/v1/admin/makerspace/{space.pk}/qr-print-batches", {"title": "New"}, format="json")
    added = client.post(f"/api/v1/admin/qr-print-batches/{batch.pk}/items", {"qr_code_id": qr.pk}, format="json")

    _outcome(created, "qr_print_batches", enabled)
    _outcome(added, "qr_print_batches", enabled)
    assert QrPrintBatch.objects.filter(title="New").exists() is enabled
    assert QrPrintBatchItem.objects.filter(batch=batch).exists() is enabled


def _stocktake(space, status, **extra):
    return StocktakeSession.objects.create(makerspace=space, status=status, **extra)


@pytest.mark.parametrize("enabled", [False, True])
def test_stocktake_workflow_steps_recheck_the_module_under_the_lock(raced, enabled):
    space, client = _setup(f"d4-stocktake-{enabled}".lower(), "stocktake", enabled)
    product = InventoryProduct.objects.create(makerspace=space, name="Pliers", total_quantity=3, available_quantity=3)
    counter = User.objects.create_user(username=f"{space.slug}-counter", email=f"{space.slug}-c@example.test")
    counting = _stocktake(space, StocktakeSession.Status.COUNTING)
    to_complete = _stocktake(space, StocktakeSession.Status.COUNTING)
    completed = _stocktake(space, StocktakeSession.Status.COMPLETED, completed_by=counter)
    approved = _stocktake(space, StocktakeSession.Status.APPROVED, completed_by=counter)
    base = "/api/v1/admin/stocktakes"

    responses = {
        "create": client.post(f"/api/v1/admin/makerspace/{space.pk}/stocktakes", {"notes": "new"}, format="json"),
        "count": client.post(
            f"{base}/{counting.pk}/count-lines", {"product_id": product.pk, "counted_quantity": 3}, format="json"
        ),
        "complete": client.post(f"{base}/{to_complete.pk}/complete", {}, format="json"),
        "approve": client.post(f"{base}/{completed.pk}/approve", {}, format="json"),
        "apply": client.post(f"{base}/{approved.pk}/apply-adjustments", {}, format="json"),
    }

    for step, response in responses.items():
        _outcome(response, "stocktake", enabled)
    statuses = {
        session.pk: session.status
        for session in StocktakeSession.objects.filter(pk__in=[to_complete.pk, completed.pk, approved.pk])
    }
    assert StocktakeSession.objects.filter(notes="new").exists() is enabled
    assert StocktakeLine.objects.filter(stocktake=counting).exists() is enabled
    if enabled:
        assert statuses == {to_complete.pk: "completed", completed.pk: "approved", approved.pk: "applied"}
    else:
        assert statuses == {to_complete.pk: "counting", completed.pk: "completed", approved.pk: "approved"}


@pytest.mark.parametrize("enabled", [False, True])
def test_asset_generation_and_unit_qr_recheck_asset_units_under_the_lock(raced, enabled):
    space, client = _setup(f"d4-assets-{enabled}".lower(), "asset_units", enabled)
    product = InventoryProduct.objects.create(
        makerspace=space, name="Scope", tracking_mode=TrackingMode.INDIVIDUAL, total_quantity=0, available_quantity=0,
    )
    unit_product = InventoryProduct.objects.create(
        makerspace=space, name="Meter", tracking_mode=TrackingMode.INDIVIDUAL, total_quantity=1, available_quantity=1,
    )
    asset = InventoryAsset.objects.create(makerspace=space, product=unit_product, asset_tag="MTR-1")

    generated = client.post(f"/api/v1/admin/products/{product.pk}/assets/generate", {"count": 2}, format="json")
    unit_qr = client.post(f"/api/v1/admin/assets/{asset.pk}/qr", {}, format="json")

    _outcome(generated, "asset_units", enabled)
    _outcome(unit_qr, "asset_units", enabled)
    assert InventoryAsset.objects.filter(product=product).count() == (2 if enabled else 0)
    assert QrCode.objects.filter(
        target_type=QrCode.TargetType.ASSET, target_id=asset.pk
    ).exists() is enabled
