"""F4 + M3: tracking_mode changes only through the Availability module's guarded path."""
import pytest
from django.contrib.admin.sites import site
from django.test import RequestFactory

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.serializers_inventory_products import InventoryProductAdminUpdateSerializer
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from tests.handout_roles import make_handout_member
from tests.return_helpers import authenticated_client, make_member, make_product, make_space, make_user

pytestmark = pytest.mark.django_db

OWNED = (
    "tracking_mode",
    "total_quantity",
    "available_quantity",
    "reserved_quantity",
    "issued_quantity",
    "damaged_quantity",
    "lost_quantity",
    "needs_fix_quantity",
)


def _patch(user, product, data):
    return authenticated_client(user).patch(
        f"/api/v1/admin/inventory/{product.id}", data, format="json"
    )


def _generate(user, product, count=1):
    return authenticated_client(user).post(
        f"/api/v1/admin/products/{product.id}/assets/generate", {"count": count}, format="json"
    )


def test_patch_refuses_tracking_mode_change_while_product_holds_stock():
    makerspace = make_space("tm-stock")
    manager = make_member("tm-stock-sm", makerspace)
    product = make_product(makerspace, total_quantity=4, available_quantity=4)

    response = _patch(manager, product, {"tracking_mode": TrackingMode.INDIVIDUAL})

    assert response.status_code == 409
    assert response.data["code"] == "tracking_mode_locked"
    product.refresh_from_db()
    assert product.tracking_mode == TrackingMode.QUANTITY


def test_patch_refuses_switching_individual_product_with_assets():
    makerspace = make_space("tm-assets")
    manager = make_member("tm-assets-sm", makerspace)
    product = make_product(
        makerspace, tracking_mode=TrackingMode.INDIVIDUAL, total_quantity=0, available_quantity=0
    )
    InventoryAsset.objects.create(
        makerspace=makerspace, product=product, asset_tag="TM-1", status=InventoryAsset.Status.LOST
    )

    response = _patch(manager, product, {"tracking_mode": TrackingMode.QUANTITY})

    assert response.status_code == 409
    product.refresh_from_db()
    assert product.tracking_mode == TrackingMode.INDIVIDUAL


def test_patch_switches_an_empty_product():
    makerspace = make_space("tm-empty")
    manager = make_member("tm-empty-sm", makerspace)
    product = make_product(makerspace, total_quantity=0, available_quantity=0)

    response = _patch(manager, product, {"tracking_mode": TrackingMode.INDIVIDUAL, "name": "Scope"})

    assert response.status_code == 200, response.data
    product.refresh_from_db()
    assert (product.tracking_mode, product.name) == (TrackingMode.INDIVIDUAL, "Scope")


def test_patch_never_writes_back_stale_quantity_buckets():
    makerspace = make_space("tm-stale")
    product = make_product(makerspace, total_quantity=10, available_quantity=10)
    stale = InventoryProduct.objects.get(pk=product.pk)
    InventoryProduct.objects.filter(pk=product.pk).update(available_quantity=7, issued_quantity=3)

    serializer = InventoryProductAdminUpdateSerializer(stale, data={"name": "Renamed"}, partial=True)
    assert serializer.is_valid(), serializer.errors
    serializer.save()

    product.refresh_from_db()
    assert (product.name, product.available_quantity, product.issued_quantity) == ("Renamed", 7, 3)


def test_bulk_update_without_tracking_column_keeps_individual_mode():
    makerspace = make_space("tm-bulk-keep")
    manager = make_member("tm-bulk-keep-sm", makerspace)
    product = make_product(
        makerspace, name="Drill", tracking_mode=TrackingMode.INDIVIDUAL, total_quantity=0, available_quantity=0
    )

    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/apply",
        {"rows": [{"name": "Drill", "total_quantity": "0", "available_quantity": "0", "description": "x"}]},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["updated"] == 1
    product.refresh_from_db()
    assert product.tracking_mode == TrackingMode.INDIVIDUAL


def test_bulk_update_tracking_change_on_stocked_product_is_a_row_error():
    makerspace = make_space("tm-bulk-refuse")
    manager = make_member("tm-bulk-refuse-sm", makerspace)
    product = make_product(makerspace, name="Saw", total_quantity=3, available_quantity=3)

    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/apply",
        {
            "rows": [
                {"name": "Saw", "total_quantity": "3", "available_quantity": "3", "tracking_mode": "individual"}
            ],
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["updated"] == 0
    assert "tracking mode" in response.data["errors"][0]["errors"]["__all__"]
    product.refresh_from_db()
    assert product.tracking_mode == TrackingMode.QUANTITY


def test_asset_generation_refuses_to_convert_a_stocked_quantity_product():
    makerspace = make_space("tm-gen-stock")
    manager = make_member("tm-gen-stock-sm", makerspace)
    product = make_product(makerspace, total_quantity=5, available_quantity=5)

    response = _generate(manager, product)

    assert response.status_code == 409
    product.refresh_from_db()
    assert (product.tracking_mode, product.total_quantity) == (TrackingMode.QUANTITY, 5)
    assert not InventoryAsset.objects.filter(product=product).exists()


def test_asset_generation_conversion_needs_edit_inventory():
    makerspace = make_space("tm-gen-qr")
    qr_only = make_handout_member(
        "tm-gen-qr-user",
        makerspace,
        slug="qr-only",
        actions=(rbac.Action.VIEW_INVENTORY, rbac.Action.MANAGE_QR),
    )
    product = make_product(makerspace, total_quantity=0, available_quantity=0)

    assert _generate(qr_only, product).status_code == 403
    product.refresh_from_db()
    assert product.tracking_mode == TrackingMode.QUANTITY

    manager = make_member("tm-gen-qr-sm", makerspace)
    assert _generate(manager, product, count=2).status_code == 201
    product.refresh_from_db()
    assert (product.tracking_mode, product.total_quantity, product.available_quantity) == (
        TrackingMode.INDIVIDUAL, 2, 2,
    )
    # Adding units to an already-individual product stays a MANAGE_QR action.
    assert _generate(qr_only, product).status_code == 201


def test_control_admin_change_form_makes_owned_fields_read_only():
    makerspace = make_space("tm-control")
    superadmin = make_user("tm-control-sa", role=User.Role.SUPERADMIN, is_superuser=True, is_staff=True)
    product = make_product(makerspace)
    request = RequestFactory().get("/control/")
    request.user = superadmin
    model_admin = site._registry[InventoryProduct]

    change_readonly = set(model_admin.get_readonly_fields(request, product))
    add_readonly = set(model_admin.get_readonly_fields(request, None))

    assert set(OWNED) <= change_readonly
    assert not set(OWNED) & add_readonly
    assert set(availability.AVAILABILITY_OWNED_FIELDS) == set(OWNED)
    form_fields = model_admin.get_form(request, product).base_fields
    assert not set(OWNED) & set(form_fields)
