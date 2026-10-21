import pytest
from django.db import IntegrityError

from apps.inventory.models import InventoryProduct
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def import_apply_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/apply"


def test_bulk_import_apply_reports_row_integrity_error_and_continues(monkeypatch):
    makerspace = make_space("bulk-hardening-partial")
    admin = make_member("bulk-hardening-partial-admin", makerspace)
    original_get_or_create = InventoryProduct.objects.get_or_create

    def flaky_get_or_create(*args, **kwargs):
        if kwargs.get("name") == "Broken Meter":
            raise IntegrityError("forced inventory conflict")
        return original_get_or_create(*args, **kwargs)

    monkeypatch.setattr(InventoryProduct.objects, "get_or_create", flaky_get_or_create)

    response = authenticated_client(admin).post(
        import_apply_url(makerspace),
        {
            "rows": [
                {"name": "Good Meter", "total_quantity": "2", "available_quantity": "2"},
                {"name": "Broken Meter", "total_quantity": "1", "available_quantity": "1"},
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["applied"] is True
    assert response.data["partial"] is True
    assert response.data["created"] == 1
    assert response.data["updated"] == 0
    assert response.data["summary"]["errors"] == 1
    assert response.data["errors"] == [
        {"row": 3, "errors": {"__all__": "forced inventory conflict"}}
    ]
    assert response.data["rows"][1]["action"] == "error"
    assert InventoryProduct.objects.filter(makerspace=makerspace, name="Good Meter").exists()
    assert not InventoryProduct.objects.filter(makerspace=makerspace, name="Broken Meter").exists()


def test_bulk_import_apply_happy_path_still_creates_all_rows():
    makerspace = make_space("bulk-hardening-happy")
    admin = make_member("bulk-hardening-happy-admin", makerspace)

    response = authenticated_client(admin).post(
        import_apply_url(makerspace),
        {
            "rows": [
                {"name": "Calipers", "total_quantity": "2", "available_quantity": "2"},
                {"name": "Scope", "total_quantity": "1", "available_quantity": "1"},
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["applied"] is True
    assert response.data["partial"] is False
    assert response.data["created"] == 2
    assert response.data["updated"] == 0
    assert InventoryProduct.objects.filter(makerspace=makerspace).count() == 2


def _apply(admin, makerspace, rows):
    return authenticated_client(admin).post(import_apply_url(makerspace), {"rows": rows}, format="json")


def test_bulk_import_refuses_workflow_stock_on_a_new_product():
    # M4: a new product cannot arrive with reservations/loans/losses no workflow recorded.
    makerspace = make_space("bulk-hardening-buckets")
    admin = make_member("bulk-hardening-buckets-admin", makerspace)

    response = _apply(
        admin,
        makerspace,
        [{"name": "Meter", "total_quantity": "3", "available_quantity": "1", "reserved_quantity": "1", "issued_quantity": "1"}],
    )

    assert response.status_code == 200
    assert response.data["applied"] is False
    assert set(response.data["errors"][0]["errors"]) == {"reserved_quantity", "issued_quantity"}
    assert not InventoryProduct.objects.filter(makerspace=makerspace, name="Meter").exists()


def test_bulk_import_bounds_quantities():
    makerspace = make_space("bulk-hardening-bounds")
    admin = make_member("bulk-hardening-bounds-admin", makerspace)

    response = _apply(admin, makerspace, [{"name": "Washers", "total_quantity": "99999999999", "available_quantity": "1"}])

    assert response.status_code == 200
    assert response.data["applied"] is False
    assert "total_quantity" in response.data["errors"][0]["errors"]


def test_bulk_import_image_key_goes_through_finalize(monkeypatch):
    from apps.inventory import public_image_storage

    makerspace = make_space("bulk-hardening-image")
    admin = make_member("bulk-hardening-image-admin", makerspace)
    missing = f"items/{makerspace.id}/never-uploaded.png"
    good = f"items/{makerspace.id}/uploaded.png"
    finalized = []

    def fake_finalize(object_key):
        finalized.append(object_key)
        if object_key == missing:
            return public_image_storage.FinalizeResult("missing", None)
        return public_image_storage.FinalizeResult("ok", 2048)

    monkeypatch.setattr(public_image_storage, "finalize_upload", fake_finalize)
    monkeypatch.setattr(public_image_storage, "sniff_is_valid_image", lambda object_key: True)

    response = _apply(
        admin,
        makerspace,
        [
            {"name": "Ghost", "total_quantity": "1", "available_quantity": "1", "image_key": missing},
            {"name": "Real", "total_quantity": "1", "available_quantity": "1", "image_key": good},
        ],
    )

    assert response.status_code == 200
    assert response.data["created"] == 1
    assert response.data["errors"][0]["row"] == 2
    assert finalized == [missing, good]
    assert not InventoryProduct.objects.filter(makerspace=makerspace, name="Ghost").exists()
    assert InventoryProduct.objects.get(makerspace=makerspace, name="Real").image_key == good


def test_bulk_import_update_with_blank_image_keeps_the_current_image():
    makerspace = make_space("bulk-hardening-keep-image")
    admin = make_member("bulk-hardening-keep-image-admin", makerspace)
    key = f"items/{makerspace.id}/current.png"
    InventoryProduct.objects.create(
        makerspace=makerspace, name="Lamp", total_quantity=1, available_quantity=1, image_key=key
    )

    response = _apply(admin, makerspace, [{"name": "Lamp", "total_quantity": "1", "available_quantity": "1", "image_key": ""}])

    assert response.status_code == 200
    assert response.data["updated"] == 1
    assert InventoryProduct.objects.get(makerspace=makerspace, name="Lamp").image_key == key


def test_bulk_import_refuses_quantities_on_a_new_individual_tracked_product():
    # Individual counts come from asset rows and an import creates none, so any quantity
    # on a new individual product is phantom stock the next reconcile would zero.
    makerspace = make_space("bulk-hardening-individual")
    admin = make_member("bulk-hardening-individual-admin", makerspace)
    rows = [
        {"name": "Scope", "tracking_mode": "individual", "total_quantity": "2", "available_quantity": "2"},
        {"name": "Probe", "tracking_mode": "individual", "total_quantity": "0", "available_quantity": "0"},
    ]

    preview = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/preview",
        {"rows": rows}, format="json",
    )
    applied = _apply(admin, makerspace, rows)

    assert preview.status_code == 200, preview.data
    assert preview.data["valid"] is False
    assert preview.data["errors"][0]["row"] == 2
    assert set(preview.data["errors"][0]["errors"]) == {"total_quantity", "available_quantity"}
    assert [row["action"] for row in preview.data["rows"]] == ["error", "create"]
    assert applied.status_code == 200
    assert applied.data["applied"] is False
    assert not InventoryProduct.objects.filter(makerspace=makerspace).exists()

    zero_only = _apply(admin, makerspace, rows[1:])

    assert zero_only.data["created"] == 1, zero_only.data
    assert InventoryProduct.objects.get(makerspace=makerspace, name="Probe").tracking_mode == "individual"
