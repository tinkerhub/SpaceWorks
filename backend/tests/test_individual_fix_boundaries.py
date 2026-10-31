"""Aggregate fix entry points must never manufacture individual-unit stock."""
import pytest
from django.contrib.messages import get_messages
from django.db import transaction
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, TrackingMode
from apps.operations.models import InventoryAdjustment
from tests.inventory_lending_evidence_helpers import domain_snapshot
from tests.inventory_lending_helpers import make_lab
from tests.test_admin_parity_actions import admin_client, make_superadmin, post_action

pytestmark = pytest.mark.django_db


def fix_url(asset):
    return f"/api/v1/admin/assets/{asset.pk}/fix-status"


def aggregate_url(product):
    return f"/api/v1/admin/inventory/{product.pk}/needs-fix"


def park_unit(lab):
    """Canonical fixture movement; no fabricated asset status or product buckets."""
    with transaction.atomic():
        asset = InventoryAsset.objects.select_for_update().get(pk=lab.assets[0].pk)
        availability.move_asset_status(asset, InventoryAsset.Status.MAINTENANCE)
    lab.assets[0].refresh_from_db()
    lab.product.refresh_from_db()
    assert lab.assets[0].status == InventoryAsset.Status.MAINTENANCE
    assert (lab.product.available_quantity, lab.product.needs_fix_quantity) == (0, 1)


def fix_snapshot(lab):
    result = domain_snapshot(lab)
    result["all_audits"] = list(AuditLog.objects.filter(
        makerspace=lab.space,
    ).order_by("pk").values())
    result["adjustments"] = list(InventoryAdjustment.objects.filter(
        makerspace=lab.space,
    ).order_by("pk").values())
    return result


def assert_unit_guidance(detail):
    assert "inventory item's individual units" in str(detail)
    assert "QR Tools" not in str(detail)


@pytest.mark.parametrize("action", ["repair", "scrap", "shelve"])
def test_aggregate_api_refuses_individual_stock(monkeypatch, settings, action):
    lab = make_lab(monkeypatch, settings, total=1, tracking_mode=TrackingMode.INDIVIDUAL)
    if action != "shelve":
        park_unit(lab)
    before = fix_snapshot(lab)

    response = lab.client.post(
        aggregate_url(lab.product), {"action": action, "quantity": 1}, format="json",
    )

    assert response.status_code == 400, response.data
    assert_unit_guidance(response.data)
    assert fix_snapshot(lab) == before


@pytest.mark.parametrize("action,service", [
    ("repair", availability.repair_from_needs_fix),
    ("scrap", availability.scrap_from_needs_fix),
    ("shelve", availability.move_available_to_needs_fix),
], ids=["repair", "scrap", "shelve"])
def test_central_helper_reads_locked_mode_despite_stale_caller(monkeypatch, settings, action, service):
    lab = make_lab(monkeypatch, settings, total=1, tracking_mode=TrackingMode.INDIVIDUAL)
    if action != "shelve":
        park_unit(lab)
    before = fix_snapshot(lab)
    # Only the caller's detached Python state lies; the actual row stays individual.
    lab.product.tracking_mode = TrackingMode.QUANTITY

    with pytest.raises(availability.InsufficientStock) as error:
        with transaction.atomic():
            service(lab.product, 1)

    assert_unit_guidance(error.value)
    assert fix_snapshot(lab) == before
    lab.product.refresh_from_db()
    assert lab.product.tracking_mode == TrackingMode.INDIVIDUAL


@pytest.mark.parametrize("action", ["repair", "scrap"])
def test_control_action_refuses_individual_stock(monkeypatch, settings, action):
    lab = make_lab(monkeypatch, settings, total=1, tracking_mode=TrackingMode.INDIVIDUAL)
    park_unit(lab)
    client = admin_client(make_superadmin("individual-fix-control"))
    before = fix_snapshot(lab)

    response = post_action(
        client, reverse("admin:inventory_inventoryproduct_changelist"),
        f"{action}_needs_fix", lab.product, apply="1", quantity="1",
    )

    assert response.status_code == 200
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert any("inventory item's individual units" in message for message in messages)
    assert fix_snapshot(lab) == before


def test_quantity_api_fix_cycle_still_moves_buckets_and_audits(monkeypatch, settings):
    lab = make_lab(monkeypatch, settings, total=2)
    # Shelve, repair, shelve and scrap exercise all three helpers with valid stock.
    for action, expected in [
        ("shelve", (2, 1, 1)), ("repair", (2, 2, 0)),
        ("shelve", (2, 1, 1)), ("scrap", (1, 1, 0)),
    ]:
        previous = set(AuditLog.objects.filter(makerspace=lab.space).values_list("pk", flat=True))
        response = lab.client.post(
            aggregate_url(lab.product), {"action": action, "quantity": 1}, format="json",
        )
        assert response.status_code == 200, response.data
        lab.product.refresh_from_db()
        assert (lab.product.total_quantity, lab.product.available_quantity,
                lab.product.needs_fix_quantity) == expected
        assert (lab.product.reserved_quantity, lab.product.issued_quantity,
                lab.product.damaged_quantity, lab.product.lost_quantity) == (0, 0, 0, 0)
        entry = AuditLog.objects.filter(makerspace=lab.space).exclude(pk__in=previous).get()
        assert entry.action == f"inventory.needs_fix_{action}"
        assert entry.actor_id == lab.actor.pk and entry.target_id == str(lab.product.pk)
        assert entry.meta == {"quantity": 1}
    assert not lab.product.assets.exists()
    assert not InventoryAdjustment.objects.filter(makerspace=lab.space).exists()
