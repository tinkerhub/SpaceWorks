"""Local fixtures and persisted-state checks for the full-audit B regressions."""

from types import SimpleNamespace

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import Box, QrCode
from apps.inventory.models import Category, InventoryAsset, InventoryProduct, TrackingMode
from apps.operations.models import (
    InventoryAdjustment, QrPrintBatch, QrPrintBatchItem, StocktakeLedgerEntry,
    StocktakeLine, StocktakeSession, StockTransfer, StockTransferLine,
)
from tests.return_helpers import (
    authenticated_client, make_box, make_member, make_product, make_space, make_user,
)


def operation_state():
    """Include complete rows so updates, not just insertions, are detected."""
    models = (
        Category, InventoryProduct, InventoryAsset, Box, QrCode, QrPrintBatch,
        QrPrintBatchItem, StockTransfer, StockTransferLine, StocktakeSession,
        StocktakeLine, StocktakeLedgerEntry, InventoryAdjustment, AuditLog,
    )
    return {model.__name__: list(model.objects.order_by("pk").values()) for model in models}


def assert_not_found(response):
    assert response.status_code == 404, response.data
    assert response.data["detail"].code == "not_found"


def inventory_context():
    source = make_space("audit-b-source")
    destination = make_space("audit-b-destination")
    foreign = make_space("audit-b-foreign")
    actor = make_user("audit-b-super", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    counter = make_member(
        "audit-b-counter", source, membership_role="inventory_manager", role=User.Role.REQUESTER,
    )
    reviewer = make_member("audit-b-reviewer", source, role=User.Role.REQUESTER)
    product = make_product(source, name="Quantity meter")
    individual = make_product(
        source, name="Unit meter", tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1, available_quantity=1,
    )
    asset = InventoryAsset.objects.create(makerspace=source, product=individual, asset_tag="AUDIT-B-1")
    foreign_product = make_product(
        foreign, tracking_mode=TrackingMode.INDIVIDUAL, total_quantity=1, available_quantity=1,
    )
    foreign_asset = InventoryAsset.objects.create(
        makerspace=foreign, product=foreign_product, asset_tag="AUDIT-B-FOREIGN",
    )
    return SimpleNamespace(
        source=source, destination=destination, foreign=foreign, actor=actor,
        counter=counter, reviewer=reviewer, product=product, individual=individual,
        asset=asset, foreign_product=foreign_product, foreign_asset=foreign_asset,
        source_box=make_box(source), destination_box=make_box(destination),
        foreign_box=make_box(foreign), client=authenticated_client(actor),
    )
