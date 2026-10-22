"""Tenant-origin scoping for the QR flows, asset warranty and staff manager lists.

Production's staff site is a tenant origin, so a route the origin registry cannot place
is a 403 for everyone. These routes carry their tenant in the body (`makerspace_id`) or
in the scanned payload's own QR row. The actor here belongs to BOTH tenants, so RBAC
alone would allow every call: each refusal below is the origin scope, and each refusal
must look the same whether the target is foreign or does not exist.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db


def _space(slug):
    return Makerspace.objects.create(
        name=slug, slug=slug, frontend_domain=f"{slug}.example.test",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )


def _user(username):
    return User.objects.create_user(
        username=username, email=f"{username}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )


def _origin(space):
    return {"HTTP_ORIGIN": f"https://{space.frontend_domain}"}


def _stock(space):
    product = InventoryProduct.objects.create(
        makerspace=space, name=f"{space.slug} drill", total_quantity=2, available_quantity=2,
    )
    unit_product = InventoryProduct.objects.create(
        makerspace=space, name=f"{space.slug} scope", tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1, available_quantity=1,
    )
    asset = InventoryAsset.objects.create(
        makerspace=space, product=unit_product, asset_tag=f"{space.slug}-1"
    )
    qr = QrCode.objects.create(
        makerspace=space, target_type=QrCode.TargetType.PRODUCT, target_id=product.pk
    )
    return product, asset, qr


@pytest.fixture
def tenants():
    home, other = _space("d4-qr-home"), _space("d4-qr-other")
    actor = _user("d4-qr-both")
    for space in (home, other):
        MakerspaceMembership.objects.create(
            makerspace=space, user=actor, role=MakerspaceMembership.Role.INVENTORY_MANAGER
        )
    client = APIClient()
    client.force_authenticate(actor)
    return client, home, other, _stock(home), _stock(other)


def _leaks(response, space, product, qr):
    body = str(getattr(response, "data", "")) + response.content.decode()
    return any(token in body for token in (qr.payload, product.name, space.slug))


def test_qr_resolve_follows_the_payloads_own_tenant(tenants):
    client, home, other, (home_product, _a, home_qr), (other_product, _b, other_qr) = tenants
    url = reverse("qr-resolve")

    own = client.post(url, {"payload": home_qr.payload}, format="json", **_origin(home))
    foreign = client.post(url, {"payload": other_qr.payload}, format="json", **_origin(home))
    unknown = client.post(url, {"payload": "0" * 32}, format="json", **_origin(home))
    conflicting = client.post(
        url, {"payload": home_qr.payload, "makerspace_id": other.pk},
        format="json", **_origin(home),
    )

    assert own.status_code == 200, own.data
    assert own.data["qr"]["id"] == home_qr.pk
    assert (foreign.status_code, unknown.status_code, conflicting.status_code) == (403, 403, 403)
    # Same refusal for a foreign QR as for one that exists nowhere: no existence oracle.
    assert foreign.data == unknown.data
    assert not _leaks(foreign, other, other_product, other_qr)
    assert not QrScanEvent.objects.filter(qr_code=other_qr).exists()

    # Off a tenant origin the deployment-wide behaviour is unchanged.
    unscoped = client.post(url, {"payload": other_qr.payload}, format="json")
    assert unscoped.status_code == 200, unscoped.data


def test_qr_scan_on_a_foreign_origin_records_nothing(tenants):
    client, home, other, (_hp, _ha, home_qr), (other_product, _oa, other_qr) = tenants
    url = reverse("qr-scan")

    own = client.post(url, {"payload": home_qr.payload, "context": "issue"}, format="json", **_origin(home))
    foreign = client.post(url, {"payload": other_qr.payload, "context": "issue"}, format="json", **_origin(home))
    missing = client.post(url, {"context": "issue"}, format="json", **_origin(home))

    assert own.status_code == 201, own.data
    assert (foreign.status_code, missing.status_code) == (403, 403)
    assert not _leaks(foreign, other, other_product, other_qr)
    assert not QrScanEvent.objects.filter(qr_code=other_qr).exists()
    assert QrScanEvent.objects.filter(qr_code=home_qr).count() == 1


def test_qr_create_routes_need_a_body_tenant_matching_the_origin(tenants):
    client, home, other, (home_product, _ha, _hq), (other_product, _oa, _oq) = tenants
    tools = reverse("qr-tools")
    before = QrCode.objects.count()

    own_tool = client.post(tools, {"makerspace_id": home.pk, "product_id": home_product.pk}, format="json", **_origin(home))
    foreign_tool = client.post(tools, {"makerspace_id": other.pk, "product_id": other_product.pk}, format="json", **_origin(home))
    hintless_tool = client.post(tools, {"product_id": home_product.pk}, format="json", **_origin(home))

    assert own_tool.status_code == 201, own_tool.data
    assert (foreign_tool.status_code, hintless_tool.status_code) == (403, 403)
    assert QrCode.objects.count() == before  # the existing product QR was reused

    for name in ("qr-boxes", "qr-containers"):
        url = reverse(name)
        own = client.post(url, {"makerspace_id": home.pk, "label": f"{name} bin"}, format="json", **_origin(home))
        foreign = client.post(url, {"makerspace_id": other.pk, "label": f"{name} bin"}, format="json", **_origin(home))

        assert own.status_code == 201, (name, own.data)
        assert foreign.status_code == 403, name
        assert not Box.objects.filter(makerspace=other).exists(), name


def test_asset_warranty_is_reachable_only_on_the_assets_own_origin(tenants):
    client, home, other, (_hp, home_asset, _hq), (other_product, other_asset, other_qr) = tenants

    own = client.get(reverse("admin-asset-warranty", args=[home_asset.pk]), **_origin(home))
    foreign = client.get(reverse("admin-asset-warranty", args=[other_asset.pk]), **_origin(home))

    assert own.status_code == 200, own.data
    assert foreign.status_code == 403
    assert not _leaks(foreign, other, other_product, other_qr)


@pytest.mark.parametrize("tag, url_name, role", [
    ("im", "admin-users-inventory-managers", MakerspaceMembership.Role.INVENTORY_MANAGER),
    ("mm", "admin-users-machine-managers", MakerspaceMembership.Role.MACHINE_MANAGER),
])
def test_manager_lists_on_a_tenant_origin_hold_no_other_tenant_rows(tag, url_name, role):
    home, other = _space(f"d4-list-home-{tag}"), _space(f"d4-list-other-{tag}")
    manager = _user(f"d4-list-sm-{tag}")
    for space in (home, other):
        MakerspaceMembership.objects.create(
            makerspace=space, user=manager, role=MakerspaceMembership.Role.SPACE_MANAGER
        )
        MakerspaceMembership.objects.create(
            makerspace=space, user=_user(f"{space.slug}-staff"), role=role
        )
    client = APIClient()
    client.force_authenticate(manager)
    url = reverse(url_name)

    scoped = client.get(url, **_origin(home))
    unscoped = client.get(url)
    foreign_hint = client.get(url, {"makerspace_id": other.pk}, **_origin(home))

    def ids(response):
        rows = response.data["results"] if isinstance(response.data, dict) else response.data
        return {row["makerspace_id"] for row in rows}

    assert scoped.status_code == 200, scoped.data
    assert ids(scoped) == {home.pk}
    assert ids(unscoped) == {home.pk, other.pk}
    assert foreign_hint.status_code == 403
