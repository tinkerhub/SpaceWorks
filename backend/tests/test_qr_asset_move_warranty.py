"""A cross-makerspace asset move carries the asset's warranty with it.

Warranty.clean requires the warranty and its asset to share a makerspace; before the
fix the move re-tenanted the asset and left the warranty (and its documents) behind
in the source space.
"""

import pytest

from apps.audit.models import AuditLog
from apps.warranty.models import Warranty, WarrantyDocument
from tests.test_qr_asset_move_core import _move_payload, _move_response, _move_setup

pytestmark = pytest.mark.django_db


def test_asset_move_moves_the_warranty_to_the_destination():
    source, dest, actor, _product, asset, qr = _move_setup("asset-move-warranty")
    warranty = Warranty.objects.create(makerspace=source, asset=asset, vendor_name="Acme")
    document = WarrantyDocument.objects.create(
        warranty=warranty,
        object_key=f"warranty/{source.id}/receipt.pdf",
        original_filename="receipt.pdf",
        content_type="application/pdf",
        size_bytes=10,
    )

    response = _move_response(actor, qr, _move_payload(asset, dest))

    assert response.status_code == 200
    warranty.refresh_from_db()
    asset.refresh_from_db()
    assert warranty.makerspace_id == dest.id == asset.makerspace_id
    warranty.full_clean()
    assert list(dest.warranties.all()) == [warranty]
    assert not source.warranties.exists()
    assert list(warranty.documents.all()) == [document]
    audit = AuditLog.objects.get(action="inventory.asset_moved_makerspace")
    assert audit.meta["warranty_id"] == warranty.id


def test_asset_move_without_warranty_records_no_warranty_id():
    _source, dest, actor, _product, asset, qr = _move_setup("asset-move-no-warranty")

    response = _move_response(actor, qr, _move_payload(asset, dest))

    assert response.status_code == 200
    assert not Warranty.objects.exists()
    audit = AuditLog.objects.get(action="inventory.asset_moved_makerspace")
    assert "warranty_id" not in audit.meta
