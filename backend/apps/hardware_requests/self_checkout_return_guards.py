from apps.hardware_requests.workflow_errors import ReturnValidationError
from apps.inventory.models import InventoryAsset


def lock_loan_assets_for_return(loan, makerspace):
    """Lock a self-checkout loan's unit assets and refuse an inconsistent return.

    The return credits every outstanding unit back to `available` and flips the asset
    rows to AVAILABLE, so it is only sound while each unit is still recorded as out
    (ISSUED). A unit staff shelved, damaged, marked lost or removed while it was out has
    already left the issued bucket; returning it again would double-count the product
    buckets and resurrect the asset. Runs before any mutation so nothing is half-applied.
    """
    asset_ids = [int(asset_id) for asset_id in (loan.asset_ids or [])]
    if not asset_ids:
        return []
    assets = list(
        InventoryAsset.objects.select_for_update()
        .filter(pk__in=asset_ids, makerspace=makerspace)
        .order_by("pk")
    )
    if len(assets) != len(set(asset_ids)) or any(
        asset.status != InventoryAsset.Status.ISSUED for asset in assets
    ):
        raise ReturnValidationError(
            "A unit on this loan is no longer recorded as checked out; ask staff to "
            "process this return."
        )
    return assets
