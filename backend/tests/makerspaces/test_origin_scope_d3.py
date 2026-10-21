"""Origin-scope registry: every admin route classified, and each new entry resolved.

A tenant custom domain hard-scopes a browser staff request to its makerspace. A route the
registry does not know is refused there, which is safe but makes it unreachable; a route
registered against the WRONG tenant field is a cross-tenant hole. So the registry is
checked both ways: exhaustively (every admin `url_name` must be deliberately classified,
including the ones that stay blocked) and per route (own origin allowed, foreign origin
refused, NULL-tenant rows refused).
"""

import re
import uuid

import pytest
from django.test import RequestFactory
from django.urls import URLResolver, get_resolver, resolve, reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.apiclients.models import ApiClient
from apps.backup.models import BackupArchive
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.origin_scope import staff_origin_scope_allows
from apps.makerspaces.origin_scope_routes import (
    BODY_TARGET_ROUTES,
    MAKERSPACE_KWARG_ROUTES,
    MODEL_LOOKUPS,
    NATIVE_HEADER_GLOBAL_ROUTES,
    ORIGIN_FILTERED_ROUTES,
    QR_PAYLOAD_ROUTES,
    QUERY_SCOPED_ROUTES,
    TARGET_SET_LOOKUPS,
    model_lookup_kwarg,
)


ADMIN_PREFIX = "api/v1/admin/"
GLOBAL_ROUTES = {"admin-makerspaces"}

# Admin routes that are deliberately REFUSED on every tenant origin. Superadmin platform
# surfaces, deployment-wide aggregates and organization surfaces are not one tenant's to
# reach from that tenant's domain. The rest are listed so adding them is a decision.
BLOCKED_ROUTES = {
    # deployment aggregates -- never flattened onto one tenant's origin
    "analytics-aggregate", "report-catalog-aggregate", "report-export-aggregate",
    # superadmin platform surfaces
    "admin-platform-backup-settings", "admin-deployment-backups", "admin-platform-email-settings",
    "admin-platform-payment-settings", "admin-platform-social-auth-settings",
    "admin-restore-operations", "admin-restore-operation", "admin-restore-decision",
    "tenant-migration-deployment-identity", "tenant-migration-imports",
    "tenant-migration-import-detail", "tenant-migration-import-decisions",
    "tenant-migration-target-abort", "tenant-migration-target-activate",
    "tenant-migration-import-run", "tenant-migration-import-verification",
    "tenant-migration-pairings", "user-restrict", "user-restore-access",
    # organizations are platform entities spanning makerspaces
    "admin-organization-list", "admin-organization-detail", "admin-organization-invitations",
    "admin-organization-invitation-revoke", "admin-organization-memberships",
    "organization-analytics", "admin-organized-event-list",
    # tenant-bearing only through an unregistered object kwarg; not registered yet, so
    # refused rather than guessed (follow-up)
    "admin-event-eligible-members", "admin-event-image", "admin-machine-service-report",
}

_CONVERTER = re.compile(r"<(?:(\w+):)?(\w+)>")


def _routes():
    def walk(patterns, prefix=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, prefix + str(pattern.pattern))
            else:
                yield prefix + str(pattern.pattern), pattern.name

    return list(walk(get_resolver().url_patterns))


def _kwargs(route):
    return {name for _converter, name in _CONVERTER.findall(route)}


def _admin_routes():
    return {
        (route, name) for route, name in _routes() if route.startswith(ADMIN_PREFIX) and name
    }


def _classification(route, name):
    classes = set()
    if (
        name in MAKERSPACE_KWARG_ROUTES or "makerspace_id" in _kwargs(route)
        or name in MODEL_LOOKUPS or name in TARGET_SET_LOOKUPS or name == "admin-makerspace"
    ):
        classes.add("kwarg-scoped")
    if name in QUERY_SCOPED_ROUTES or name in ORIGIN_FILTERED_ROUTES:
        classes.add("query-scoped")
    if name in BODY_TARGET_ROUTES or name in QR_PAYLOAD_ROUTES:
        classes.add("body-scoped")
    if name in GLOBAL_ROUTES:
        classes.add("global")
    if name in BLOCKED_ROUTES:
        classes.add("blocked")
    return classes


def test_every_admin_route_is_classified_exactly_once():
    problems = {
        name: sorted(classes)
        for route, name in _admin_routes()
        if len(classes := _classification(route, name)) != 1
    }
    assert not problems, (
        "Classify each admin route as kwarg-scoped, query-scoped, body-scoped, global or blocked "
        f"(origin_scope_routes / BLOCKED_ROUTES): {problems}"
    )


def test_registry_names_real_routes_and_each_declared_kwarg_exists():
    by_name = {}
    for route, name in _routes():
        by_name.setdefault(name, set()).update(_kwargs(route))
    registered = (
        set(MAKERSPACE_KWARG_ROUTES) | set(MODEL_LOOKUPS) | set(TARGET_SET_LOOKUPS)
        | QUERY_SCOPED_ROUTES | ORIGIN_FILTERED_ROUTES | NATIVE_HEADER_GLOBAL_ROUTES
        | BODY_TARGET_ROUTES | QR_PAYLOAD_ROUTES | BLOCKED_ROUTES
    )
    assert not registered - set(by_name), "stale registry names"
    for name, kwarg in MAKERSPACE_KWARG_ROUTES.items():
        assert kwarg in by_name[name], name
    for name in MODEL_LOOKUPS:
        # The presence/verify-domain bug: registered against `pk` on a route that has no
        # `pk`, so every request was marked invalid and refused despite being registered.
        assert model_lookup_kwarg(name) in by_name[name], name


def _space(slug):
    return Makerspace.objects.create(
        name=slug, slug=slug, frontend_domain=f"{slug}.example.test",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )


def _request(path, space, method="get"):
    request = getattr(RequestFactory(), method)(path, HTTP_ORIGIN=f"https://{space.frontend_domain}")
    request.resolver_match = resolve(request.path_info)
    return request


@pytest.mark.django_db
def test_blocked_routes_are_refused_on_a_tenant_origin():
    space = _space("d3-origin-blocked")
    values = {"int": "999999", "uuid": str(uuid.uuid4()), None: "x", "slug": "x", "str": "x"}
    for route, name in sorted(_admin_routes()):
        if name not in BLOCKED_ROUTES:
            continue
        path = "/" + _CONVERTER.sub(lambda m: values.get(m.group(1), "x"), route)
        request = _request(path, space)
        assert request.resolver_match.url_name == name, path
        assert staff_origin_scope_allows(request) is False, name


def _fixtures(space, tag):
    product = InventoryProduct.objects.create(
        makerspace=space, name=f"{tag} meter", tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1, available_quantity=1,
    )
    asset = InventoryAsset.objects.create(makerspace=space, product=product, asset_tag=f"{tag}-1")
    member = User.objects.create_user(username=f"{tag}-member", email=f"{tag}-m@example.test")
    membership = MakerspaceMembership.objects.create(
        makerspace=space, user=member, role=MakerspaceMembership.Role.INVENTORY_MANAGER
    )
    client = ApiClient.objects.create(label=tag, secret_encrypted=b"x", makerspace=space)
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.MAKERSPACE, makerspace=space,
        superadmin_access_at_decision=True, object_key=f"{tag}/archive",
    )
    return {
        "admin-inventory-assets": [product.pk],
        "admin-inventory-qr-history": [product.pk],
        "asset-generate": [product.pk],
        "admin-inventory-asset-fix-status": [asset.pk],
        "admin-inventory-asset-qr-history": [asset.pk],
        "admin-asset-warranty": [asset.pk],
        "asset-qr": [asset.pk],
        "admin-membership-verify": [membership.pk],
        "admin-membership-unverify": [membership.pk],
        "admin-membership-waiver-witness": [membership.pk],
        "admin-api-client": [client.pk],
        "admin-api-client-rotate-secret": [client.pk],
        "admin-backup-download-url": [archive.pk],
        "admin-presence-sessions-current": [space.pk],
        "makerspace-verify-domain": [space.pk],
    }


@pytest.mark.django_db
def test_new_tenant_routes_resolve_on_their_own_origin_and_are_refused_elsewhere():
    home, other = _space("d3-origin-home"), _space("d3-origin-other")
    for name, args in _fixtures(home, "d3-home").items():
        path = reverse(name, args=args)
        assert staff_origin_scope_allows(_request(path, home)) is True, name
        assert staff_origin_scope_allows(_request(path, other)) is False, name


@pytest.mark.django_db
def test_null_tenant_rows_are_refused_on_every_tenant_origin():
    space = _space("d3-origin-null")
    global_client = ApiClient.objects.create(label="global", secret_encrypted=b"x")
    deployment = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT, object_key="d3/deployment-archive"
    )

    for path in (
        reverse("admin-api-client", args=[global_client.pk]),
        reverse("admin-api-client-rotate-secret", args=[global_client.pk]),
        reverse("admin-backup-download-url", args=[deployment.pk]),
    ):
        assert staff_origin_scope_allows(_request(path, space, "post")) is False, path


@pytest.mark.django_db
def test_staff_manager_lists_collapse_to_the_origin_tenant():
    home, other = _space("d3-staff-home"), _space("d3-staff-other")
    for space in (home, other):
        MakerspaceMembership.objects.create(
            makerspace=space,
            user=User.objects.create_user(username=f"{space.slug}-sm", email=f"{space.slug}@e.test"),
            role=MakerspaceMembership.Role.SPACE_MANAGER,
        )
    superadmin = User.objects.create_user(
        username="d3-staff-superadmin", email="d3-staff-superadmin@example.test",
        role=User.Role.SUPERADMIN, is_staff=True, is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(superadmin)
    url = reverse("admin-users-space-managers")

    scoped = client.get(url, HTTP_ORIGIN=f"https://{home.frontend_domain}")
    unscoped = client.get(url)
    foreign_create = client.post(
        url, {"role": "space_manager", "makerspace_id": other.pk, "username": "x"},
        format="json", HTTP_ORIGIN=f"https://{home.frontend_domain}",
    )

    rows = scoped.data["results"] if isinstance(scoped.data, dict) else scoped.data
    all_rows = unscoped.data["results"] if isinstance(unscoped.data, dict) else unscoped.data
    assert scoped.status_code == 200, scoped.data
    assert {row["makerspace_id"] for row in rows} == {home.pk}
    assert {row["makerspace_id"] for row in all_rows} >= {home.pk, other.pk}
    assert foreign_create.status_code == 403
