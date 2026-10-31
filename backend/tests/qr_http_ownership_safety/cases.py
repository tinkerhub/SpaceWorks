"""Independent eight-route acceptance facts and real HTTP payloads."""
from importlib import import_module
from types import SimpleNamespace

from django.urls import get_resolver, resolve, reverse

from tests.qr_source_safety.http_helpers import empty_product
from tests.qr_target_safety_helpers import qr_for, target


# Kept independent of the implementation registry: additions must not self-approve.
ROUTES = (
    "qr-boxes", "qr-tools", "qr-scan", "qr-resolve", "qr-revoke",
    "qr-rebind-target", "asset-generate", "asset-qr",
)
CLASSES = (
    "CreateBoxQrView", "CreateToolQrView", "QrScanView", "QrResolveView",
    "QrRevokeView", "QrRebindTargetView", "AssetGenerateView", "AssetQrView",
)
PATHS = (
    "/api/v1/admin/qr/boxes", "/api/v1/admin/qr/tools", "/api/v1/admin/qr/scan",
    "/api/v1/admin/qr/resolve", "/api/v1/admin/qr/17/revoke",
    "/api/v1/admin/qr/17/rebind-target",
    "/api/v1/admin/products/17/assets/generate", "/api/v1/admin/assets/17/qr",
)
BINDINGS = (
    ("qr-boxes", "create_box_with_qr", "apps.boxes.services.create_box_with_qr"),
    ("qr-tools", "create_tool_qr", "apps.boxes.qr_admission.create_tool_qr"),
    ("qr-scan", "admitted_qr", "apps.boxes.qr_admission.admitted_qr"),
    ("qr-resolve", "admitted_qr", "apps.boxes.qr_admission.admitted_qr"),
    ("qr-revoke", "revoke_qr_code", "apps.boxes.services.revoke_qr_code"),
    ("qr-rebind-target", "preflight_rebind", "apps.boxes.rebind.preflight_rebind"),
    ("qr-rebind-target", "rebind_qr_target", "apps.boxes.rebind.rebind_qr_target"),
    ("asset-generate", "services.generate_assets_with_qr",
     "apps.operations.services_qr_assets.generate_assets_with_qr"),
    ("asset-qr", "qr_write", "apps.boxes.qr_admission.qr_write"),
)


def declaration(route):
    index = ROUTES.index(route)
    package = "operations" if route.startswith("asset-") else "boxes"
    module = "views_qr_batches" if package == "operations" else "api_views_qr"
    barrel = "views" if package == "operations" else "api_views"
    return (f"apps.{package}.{module}.{CLASSES[index]}",
            f"apps.{package}.{barrel}.{CLASSES[index]}",
            tuple((expression, owner) for name, expression, owner in BINDINGS
                  if name == route))


def imported(path):
    module, name = path.rsplit(".", 1)
    return getattr(import_module(module), name)


def matched(route):
    return resolve(PATHS[ROUTES.index(route)])


def url_pattern(route):
    """Find the actual included URLPattern, without replacing resolve()."""
    callback = matched(route).func

    def walk(patterns):
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                yield from walk(pattern.url_patterns)
            elif pattern.name == route and pattern.callback is callback:
                yield pattern

    found = list(walk(get_resolver().url_patterns))
    assert len(found) == 1, found
    return found[0]


def prepared(lab, route, client=None):
    client = client or lab.api
    args, data, obj, qr = [], {}, None, None
    if route == "qr-boxes":
        data = {"makerspace_id": lab.home.pk, "label": "HTTP ownership box"}
    elif route == "qr-tools":
        obj = target(lab.home, "product")
        data = {"makerspace_id": lab.home.pk, "product_id": obj.pk}
    elif route == "asset-generate":
        obj = empty_product(lab.home)
        args, data = [obj.pk], {"count": 1}
    elif route == "asset-qr":
        obj = target(lab.home, "asset")
        args = [obj.pk]
    else:
        obj = target(lab.home, "product")
        qr = qr_for(lab.home, obj, "product", created_by=lab.actor)
        if route in {"qr-scan", "qr-resolve"}:
            data = {"payload": qr.payload}
            if route == "qr-scan":
                data["context"] = "inventory_check"
        else:
            args = [qr.pk]
            if route == "qr-rebind-target":
                destination = target(lab.home, "product")
                data = {"target_type": "product", "target_id": destination.pk}
    url = reverse(route, args=args)
    status = 201 if route in {"qr-boxes", "qr-tools", "qr-scan",
                              "asset-generate", "asset-qr"} else 200
    return SimpleNamespace(url=url, data=data, obj=obj, qr=qr, status=status,
                           call=lambda: client.post(url, data, format="json"))
