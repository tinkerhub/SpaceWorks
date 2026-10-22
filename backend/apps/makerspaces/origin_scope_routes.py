from django.apps import apps

from apps.makerspaces.origin_scope_model_lookups import (
    BASE_MODEL_LOOKUPS,
    TARGET_SET_LOOKUPS,
)

MAKERSPACE_KWARG_ROUTES = {
    'admin-maintenance-schedule-list-create': 'makerspace_id',
    'admin-maintenance-log-list-create': 'makerspace_id',
    'admin-bookable-space-list-create': 'makerspace_id',
    'admin-event-list-create': 'makerspace_id',
    'admin-event-series-list-create': 'makerspace_id',
    'admin-event-series-collaboration-inbox': 'makerspace_id',
    'admin-role-capabilities': 'makerspace_id',
    'admin-role-list-create': 'makerspace_id',
    'admin-role-detail': 'makerspace_id',
    'admin-machine-types': 'makerspace_id',
    'admin-machine-type-detail': 'makerspace_id',
    'admin-makerspace-provision-subdomain': 'makerspace_id',
    'admin-makerspace-subdomain-request': 'makerspace_id',
    'admin-api-settings': 'makerspace_id',
    'admin-notification-recipients': 'makerspace_id',
    'admin-notification-rules': 'makerspace_id',
    'admin-machine-service-request-list-create': 'makerspace_id',
    'admin-presence-sessions-current': 'makerspace_id',
    'makerspace-verify-domain': 'makerspace_id',
}
# These routes have no tenant-bearing path segment by design: each is a listing whose
# queryset is explicitly narrowed by the named makerspace query parameter.
QUERY_SCOPED_ROUTES = {
    'admin-api-key-requests',       # requester-owned API-key requests; ?makerspace=
    'admin-audit-logs',             # tenant audit-log listing; ?makerspace=
    'admin-membership-requests',    # tenant join-request queue; ?makerspace_id=
    'admin-memberships-roster',     # tenant membership roster; ?makerspace_id=
    'admin-needs-fix-shelf',        # tenant repair shelf; ?makerspace=
    'ledger-aggregate',             # superadmin aggregate listing; ?makerspace=
    'ledger-export-aggregate',      # matching aggregate export; ?makerspace=
}
# Listings with no tenant in the path whose VIEW narrows the queryset to the origin's
# makerspace itself (`origin_scope.staff_origin_scope`) whenever a tenant origin is
# active. Allowed without a target only because of that narrowing; a body/query
# makerspace hint, when given, must still match the origin.
ORIGIN_FILTERED_ROUTES = {
    'admin-users-space-managers',
    'admin-users-inventory-managers',
    'admin-users-machine-managers',
}
# Create routes with no tenant in the path whose serializer REQUIRES a body
# `makerspace_id` and resolves the makerspace from it. The body hint is their target: it
# must be present and match the origin, so a hintless request is refused, never guessed.
BODY_TARGET_ROUTES = {
    'qr-boxes',
    'qr-containers',
    'qr-tools',
}
# Routes keyed only by the opaque, globally-unique QR payload in the body. The payload's
# own QrCode row names the tenant; an unknown or missing payload is an invalid target
# and refused on every tenant origin (no "not found" that could differ by tenant).
QR_PAYLOAD_ROUTES = {
    'qr-resolve',
    'qr-scan',
}
NATIVE_HEADER_GLOBAL_ROUTES = {
    'auth-me',
    'device-grants',
    'device-grant-detail',
    'push-device-list-create',
    'push-device-detail',
}
REQUEST_ACTIONS = {
    'request-accept',
    'request-reject',
    'request-assign-box',
    'request-issue',
    'request-return-due',
    'request-return',
    'guest-admin-request-return',
    'request-timeline',
}
MACHINE_SERVICE_ACTIONS = {
    'admin-machine-service-request-detail',
    'admin-machine-service-request-accept',
    'admin-machine-service-request-reject',
    'admin-machine-service-request-start',
    'admin-machine-service-request-complete',
    'admin-machine-service-request-fail',
    'admin-machine-service-request-collect',
    'admin-machine-service-request-record-manual-payment',
    'admin-machine-service-file-presign',
    'admin-machine-service-file-finalize',
}
# Consumable-pool detail/adjustments are keyed only by pool pk -- unlike the sibling
# list/create route, which carries makerspaces/<int:makerspace_id>/ in its path and so
# resolves its tenant from the URL. Without an entry here they resolve as unscoped global
# endpoints and fail closed, making them unreachable from a verified tenant custom domain.
MACHINE_CONSUMABLE_POOL_ACTIONS = {
    'admin-machine-service-printer-pool-detail',
    'admin-machine-service-printer-pool-adjustments',
}
MODEL_LOOKUPS = {
    **BASE_MODEL_LOOKUPS,
    **{name: ('hardware_requests.HardwareRequest', 'makerspace_id') for name in REQUEST_ACTIONS},
    **{name: ('machines.MachineServiceRequest', 'makerspace_id') for name in MACHINE_SERVICE_ACTIONS},
    **{
        name: ('machines.MachineConsumablePool', 'makerspace_id')
        for name in MACHINE_CONSUMABLE_POOL_ACTIONS
    },
}

def request_route_targets(request, view=None):
    url_name, targets, invalid, route_recognized = _authoritative_route_targets(
        request, view
    )
    # Body-resolved routes are recognized only here, never in the authoritative
    # resolution the tenant-migration gate uses, so its locking is unchanged by them.
    if url_name in BODY_TARGET_ROUTES:
        route_recognized = True
    elif url_name in QR_PAYLOAD_ROUTES:
        route_recognized = True
        resolved = _qr_payload_makerspace_id(request)
        invalid = invalid or resolved is None
        if resolved is not None:
            targets = targets | {resolved}
    hints = []
    query = getattr(request, 'query_params', None)
    if query is None:
        query = getattr(request, 'GET', {})
    for key in ('makerspace', 'makerspace_id'):
        value = query.get(key)
        if value in (None, ''):
            continue
        parsed = _positive_int(value)
        invalid = invalid or parsed is None
        if parsed is not None:
            hints.append(parsed)
    if getattr(request, "method", "GET") not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        body = getattr(request, "data", {})
        if hasattr(body, "get"):
            for key in ("makerspace", "makerspace_id"):
                value = body.get(key)
                if value in (None, ""):
                    continue
                parsed = _positive_int(value)
                invalid = invalid or parsed is None
                if parsed is not None:
                    hints.append(parsed)

    hint_set = set(hints)
    if url_name in TARGET_SET_LOOKUPS:
        invalid = invalid or bool(hint_set - targets)
    else:
        invalid = invalid or len(targets | hint_set) > 1
    target_set = targets | hint_set
    return url_name, target_set, invalid, route_recognized


def authoritative_route_resolution(request, view=None):
    """Return non-raising authoritative targets plus whether the route is known."""
    try:
        _name, targets, invalid, recognized = _authoritative_route_targets(
            request, view
        )
    except Exception:
        return set(), False
    return (targets if recognized and not invalid else set()), recognized


def _authoritative_route_targets(request, view=None):
    match = getattr(request, 'resolver_match', None)
    url_name = getattr(match, 'url_name', '')
    kwargs = dict(getattr(match, 'kwargs', {}) or {})
    kwargs.update(getattr(view, 'kwargs', {}) or {})
    targets = set()
    invalid = False
    registered = MAKERSPACE_KWARG_ROUTES.get(url_name)
    route_recognized = bool(
        registered or 'makerspace_id' in kwargs
        or (url_name == 'admin-makerspace' and 'pk' in kwargs)
        or url_name in MODEL_LOOKUPS or url_name in TARGET_SET_LOOKUPS
        or url_name in QUERY_SCOPED_ROUTES or url_name in NATIVE_HEADER_GLOBAL_ROUTES
        or url_name in ORIGIN_FILTERED_ROUTES)
    route_value = None
    if registered:
        route_value = kwargs.get(registered)
        invalid = route_value is None
    elif 'makerspace_id' in kwargs:
        route_value = kwargs.get('makerspace_id')
    elif url_name == 'admin-makerspace' and 'pk' in kwargs:
        route_value = kwargs.get('pk')
    if route_value is not None:
        parsed = _positive_int(route_value)
        invalid = invalid or parsed is None
        if parsed is not None:
            targets.add(parsed)

    if url_name in MODEL_LOOKUPS:
        pk = kwargs.get(model_lookup_kwarg(url_name))
        resolved = _lookup_makerspace_id(url_name, pk) if pk is not None else None
        invalid = invalid or resolved is None
        if resolved is not None:
            targets.add(resolved)
    elif url_name in TARGET_SET_LOOKUPS:
        pk = kwargs.get('pk')
        invalid = invalid or pk is None
        if pk is not None:
            targets.update(_lookup_makerspace_ids(url_name, pk))
    return url_name, targets, invalid, route_recognized


def _qr_payload_makerspace_id(request):
    if getattr(request, 'method', 'GET') in {'GET', 'HEAD', 'OPTIONS', 'TRACE'}:
        return None
    body = getattr(request, 'data', {})
    payload = body.get('payload') if hasattr(body, 'get') else None
    if not isinstance(payload, str) or not payload.strip():
        return None
    # Mirrors the serializer's whitespace trim so both look up the same row.
    return (
        apps.get_model('boxes.QrCode').objects
        .filter(payload=payload.strip())
        .values_list('makerspace_id', flat=True)
        .first()
    )


def _positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 and str(parsed) == str(value).strip() else None


def model_lookup_kwarg(url_name):
    """The route kwarg a MODEL_LOOKUPS entry looks its object up by (default ``pk``)."""
    entry = MODEL_LOOKUPS[url_name]
    return entry[2] if len(entry) > 2 else 'pk'


def _lookup_makerspace_id(url_name, pk):
    model_path, field = MODEL_LOOKUPS[url_name][:2]
    model = apps.get_model(model_path)
    try:
        return model.objects.values_list(field, flat=True).get(pk=pk)
    except model.DoesNotExist:
        return None


def _lookup_makerspace_ids(url_name, pk):
    model_path, owner_field, tenant_field = TARGET_SET_LOOKUPS[url_name]
    model = apps.get_model(model_path)
    return set(
        model.objects.filter(**{owner_field: pk})
        .values_list(tenant_field, flat=True)
    )
