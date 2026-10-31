"""Exact HTTP boundary ownership; this delegates locks, never authorization."""

from importlib import import_module
from inspect import getclosurevars, isfunction, unwrap

from django.utils.module_loading import import_string

from .gate_errors import SourceMigrationGateUnavailable


SERVICE_OWNED_HTTP_BOUNDARIES = {
    "admin:makerspaces_modulepurgereceipt_retry_cleanup": (
        "apps.makerspaces.admin_module_purge_receipts.retry_cleanup_view",
        "apps.makerspaces.module_purge_receipts.retry_cleanup",
    ),
    "admin:makerspaces_purgereceipt_retry_cleanup": (
        "apps.makerspaces.admin_purge_receipts.retry_cleanup_view",
        "apps.makerspaces.purge_receipts.retry_cleanup",
    ),
    "admin:makerspaces_makerspace_purge_confirmed": (
        "apps.makerspaces.admin_purge.confirmed_purge_view",
        "apps.makerspaces.lifecycle_purge.purge",
    ),
}


def service_owns_http_boundary(request, match):
    declaration = SERVICE_OWNED_HTTP_BOUNDARIES.get(match.view_name)
    if declaration is None or request.method != "POST":
        return False
    handler, service = declaration
    if (unwrap(match.func) is not unwrap(import_string(handler))
            or not callable(import_string(service))
            or "default" not in getattr(match.func, "_non_atomic_requests", set())
            or getattr(match.func, "csrf_exempt", False)):
        raise SourceMigrationGateUnavailable("The dedicated purge boundary route is misconfigured.")
    return True


# POST only. These API owners perform authorized preflight before taking sorted
# tenant locks. They still need the middleware's shared unscoped writer boundary
# for incidental authentication writes; this table grants no permission.
# Each binding is the expression consumed by post, paired with its canonical owner.
API_OWNED_HTTP_BOUNDARIES = {
    "qr-boxes": (
        "apps.boxes.api_views_qr.CreateBoxQrView",
        "apps.boxes.api_views.CreateBoxQrView",
        (("create_box_with_qr", "apps.boxes.services.create_box_with_qr"),),
    ),
    "qr-tools": (
        "apps.boxes.api_views_qr.CreateToolQrView",
        "apps.boxes.api_views.CreateToolQrView",
        (("create_tool_qr", "apps.boxes.qr_admission.create_tool_qr"),),
    ),
    "qr-scan": (
        "apps.boxes.api_views_qr.QrScanView",
        "apps.boxes.api_views.QrScanView",
        (("admitted_qr", "apps.boxes.qr_admission.admitted_qr"),),
    ),
    "qr-resolve": (
        "apps.boxes.api_views_qr.QrResolveView",
        "apps.boxes.api_views.QrResolveView",
        (("admitted_qr", "apps.boxes.qr_admission.admitted_qr"),),
    ),
    "qr-revoke": (
        "apps.boxes.api_views_qr.QrRevokeView",
        "apps.boxes.api_views.QrRevokeView",
        (("revoke_qr_code", "apps.boxes.services.revoke_qr_code"),),
    ),
    "qr-rebind-target": (
        "apps.boxes.api_views_qr.QrRebindTargetView",
        "apps.boxes.api_views.QrRebindTargetView",
        (
            ("preflight_rebind", "apps.boxes.rebind.preflight_rebind"),
            ("rebind_qr_target", "apps.boxes.rebind.rebind_qr_target"),
        ),
    ),
    "asset-generate": (
        "apps.operations.views_qr_batches.AssetGenerateView",
        "apps.operations.views.AssetGenerateView",
        (("services.generate_assets_with_qr", "apps.operations.services_qr_assets.generate_assets_with_qr"),),
    ),
    "asset-qr": (
        "apps.operations.views_qr_batches.AssetQrView",
        "apps.operations.views.AssetQrView",
        (("qr_write", "apps.boxes.qr_admission.qr_write"),),
    ),
}


def api_owns_http_boundary(request, match):
    """Prove the resolved POST and its consumed owners, or refuse declared drift."""
    declaration = API_OWNED_HTTP_BOUNDARIES.get(getattr(match, "view_name", None))
    if declaration is None or request.method != "POST":
        return False
    try:
        canonical, alias, bindings = declaration
        view_class, post = _api_post(canonical, alias)
        _validate_api_callback(match.func, view_class)
        for expression, owner_path in bindings:
            owner = import_string(owner_path)
            parts = expression.split(".")
            bound = post.__globals__[parts[0]]
            if len(parts) == 2:
                # Generation consumes the actual services barrel, not an unused
                # independently imported generate_assets_with_qr callable.
                if bound is not import_module("apps.operations.services"):
                    raise ValueError("QR generation services module changed.")
                bound = getattr(bound, parts[1])
            if not callable(owner) or bound is not owner:
                raise ValueError("QR POST owner binding changed.")
    except Exception as exc:
        raise SourceMigrationGateUnavailable(
            "The dedicated QR API boundary route is misconfigured."
        ) from exc
    return True


def _api_post(canonical, alias):
    from rest_framework.views import APIView

    module_name, class_name = canonical.rsplit(".", 1)
    view_class = import_string(canonical)
    if (not isinstance(view_class, type) or not issubclass(view_class, APIView)
            or view_class.__module__ != module_name
            or view_class.__qualname__ != class_name
            or import_string(alias) is not view_class):
        raise ValueError("QR API class or URL-facing alias changed.")
    post = vars(view_class)["post"]
    # Do not unwrap a substituted method: the implementation actually dispatched
    # must be the canonical class's own POST, in its defining module's globals.
    if (not isfunction(post) or post.__module__ != module_name
            or post.__qualname__ != f"{class_name}.post"
            or post.__code__.co_qualname != f"{class_name}.post"
            or post.__globals__ is not vars(import_module(module_name))):
        raise ValueError("QR API POST implementation changed.")
    return view_class, post


def _validate_api_callback(callback, view_class):
    """Validate DRF's real CSRF wrapper and the class captured by its callback."""
    from rest_framework.views import APIView

    # Use the framework factory as a reference, without copying Django's view
    # implementation or accepting a callback merely because it has cls metadata.
    expected = APIView.as_view.__func__(view_class)
    core, expected_core = callback.__wrapped__, expected.__wrapped__
    for actual, reference in ((callback, expected), (core, expected_core)):
        if (not isfunction(actual) or actual.__code__ is not reference.__code__
                or actual.__globals__ is not reference.__globals__
                or actual.__defaults__ != reference.__defaults__
                or actual.__kwdefaults__ != reference.__kwdefaults__
                or actual.view_class is not view_class or actual.cls is not view_class
                or actual.view_initkwargs != {} or actual.initkwargs != {}):
            raise ValueError("QR API resolved callback changed.")
    expected_wrapper_scope = getclosurevars(expected).nonlocals
    wrapper_scope = {
        key: core if value is expected_core else value
        for key, value in expected_wrapper_scope.items()
    }
    if (getclosurevars(callback).nonlocals != wrapper_scope
            or getclosurevars(core).nonlocals != getclosurevars(expected_core).nonlocals):
        raise ValueError("QR API callback captured a different class or configuration.")
