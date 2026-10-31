"""Prepare real requests before a gate/row wait; never replace application guards."""
from types import SimpleNamespace

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.urls import reverse

from apps.inventory.models import InventoryProduct
from tests.qr_target_safety_helpers import (
    configure, jwt_client, native_client, native_form, qr_for, space, staff,
    superadmin, target,
)

API_WRITERS = ("api-box", "api-product", "api-asset", "api-scan", "api-resolve",
               "api-revoke", "api-rebind", "api-cross-product", "api-cross-asset",
               "api-generate")
NATIVE_WRITERS = ("native-edit", "native-single", "native-bulk", "native-revoke",
                  "native-rebind", "native-generate")
WRITERS = (*API_WRITERS, *NATIVE_WRITERS)
CROSS_WRITERS = ("api-cross-product", "api-cross-asset",
                 "native-cross-product", "native-cross-asset")


@pytest.fixture
def closure_lab(settings):
    configure(settings)
    home, other = space(), space()
    for tenant in (home, other):
        tenant.enabled_modules = sorted(set(tenant.enabled_modules) | {
            "qr_management", "scanner", "asset_units", "qr_print_batches", "containers",
        })
        tenant.save(update_fields=["enabled_modules"])
    root = superadmin()
    actor = staff(home)
    return SimpleNamespace(home=home, other=other, root=root, actor=actor,
                           api=jwt_client(actor), root_api=jwt_client(root),
                           native=native_client(root))


def empty_product(tenant):
    return InventoryProduct.objects.create(
        makerspace=tenant, name="Generation destination", tracking_mode="individual",
        total_quantity=0, available_quantity=0,
    )


def bulk_request(client, codes, *, action="delete_selected", query="", across=False, **extra):
    url = reverse("admin:boxes_qrcode_changelist") + query
    data = {"action": action, "select_across": str(int(across)), "post": "yes",
            ACTION_CHECKBOX_NAME: [str(qr.pk) for qr in codes], **extra}
    return lambda: client.post(url, data)


def generation_request(lab, product, *, native=False, **extra):
    if native:
        url = reverse("admin:inventory_inventoryproduct_changelist")
        data = {"action": "generate_qr_assets", "select_across": "0", "apply": "1",
                ACTION_CHECKBOX_NAME: [str(product.pk)], "count": "1", **extra}
        return lambda: lab.native.post(url, data)
    url = f"/api/v1/admin/products/{product.pk}/assets/generate"
    return lambda: lab.api.post(url, {"count": 1, **extra}, format="json")


def prepared(lab, kind, *, tenant=None, api=None):
    """Every case is valid when OPEN, including both sides of asset transfers."""
    tenant = tenant or lab.home
    api = api or (lab.root_api if "cross" in kind else lab.api)
    native = kind.startswith("native")
    obj_kind = "asset" if kind in {"api-asset", "api-cross-asset", "native-cross-asset"} else "product"
    obj = empty_product(tenant) if kind.endswith("generate") else target(tenant, obj_kind)
    case = SimpleNamespace(kind=kind, obj=obj, tenant=tenant, qr=None, destination=None,
                           actor=lab.root if native or "cross" in kind else lab.actor)
    if kind.endswith("generate"):
        case.call = generation_request(lab, obj, native=native)
        return case
    if kind == "api-box":
        case.call = lambda: api.post(reverse("qr-boxes"), {
            "makerspace_id": tenant.pk, "label": "Source-admitted box",
        }, format="json")
        return case
    if kind in {"api-product", "api-asset"}:
        case.call = lambda: api.post(reverse("qr-tools"), {
            "makerspace_id": tenant.pk, f"{obj_kind}_id": obj.pk,
        }, format="json")
        return case
    qr = case.qr = qr_for(tenant, obj, obj_kind, created_by=case.actor)
    if kind in {"api-scan", "api-resolve"}:
        data = {"payload": qr.payload}
        if kind == "api-scan":
            data["context"] = "inventory_check"
        case.call = lambda: api.post(reverse(f"qr-{kind[4:]}"), data, format="json")
    elif kind == "api-revoke":
        case.call = lambda: api.post(reverse("qr-revoke", args=[qr.pk]), {}, format="json")
    elif kind == "native-edit":
        url, data = native_form(lab.native, "boxes_qrcode", qr, created_by=lab.actor.pk)
        case.call = lambda: lab.native.post(url, data)
    elif kind == "native-single":
        url = reverse("admin:boxes_qrcode_delete", args=[qr.pk])
        case.call = lambda: lab.native.post(url, {"post": "yes"})
    elif kind in {"native-bulk", "native-revoke"}:
        case.call = bulk_request(lab.native, [qr], action=(
            "delete_selected" if kind == "native-bulk" else "revoke_selected"))
    else:
        destination = lab.other if "cross" in kind else tenant
        dest = case.destination = (empty_product(destination) if obj_kind == "asset"
                                   else target(destination, "product"))
        data = {"target_type": obj_kind, "target_id": obj.pk if obj_kind == "asset" else dest.pk}
        if obj_kind == "asset":
            data.update(destination_makerspace_id=destination.pk, destination_product_id=dest.pk)
        if native:
            changes = {"apply": "1", "target_type": obj_kind,
                       "asset_target" if obj_kind == "asset" else "product_target": data["target_id"]}
            if obj_kind == "asset":
                changes.update(destination_makerspace=destination.pk, destination_product=dest.pk)
            case.call = bulk_request(lab.native, [qr], action="rebind_selected", **changes)
        else:
            case.call = lambda: api.post(reverse("qr-rebind-target", args=[qr.pk]), data, format="json")
    return case


def success(kind):
    if kind.startswith("native"):
        return 302
    return 201 if kind in {"api-box", "api-product", "api-asset", "api-scan", "api-generate"} else 200


def event(kind):
    return {"api-box": "qr.box_created", "api-product": "qr.tool_created",
            "api-asset": "qr.tool_created", "api-scan": "qr.scanned", "api-resolve": "qr.scanned",
            "native-edit": "control.object_updated", "native-single": "control.object_deleted",
            "native-bulk": "control.object_deleted"}.get(kind, (
                "asset_units.generated" if kind.endswith("generate") else
                "inventory.asset_moved_makerspace" if kind.endswith("cross-asset") else
                "qr.revoked" if kind.endswith("revoke") else "qr.rebound"))
