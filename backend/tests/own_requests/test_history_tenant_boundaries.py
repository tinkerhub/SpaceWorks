"""Served slugs, browser origins, native selection and real API-client registry."""

import pytest
from django.test import RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.apiclients.models import ApiClient
from apps.apiclients.scope_registry import (
    LEGACY_SCOPE, TARGET_TENANT_SLUG, classify, lookup, validate_registry,
)
from tests.backup.test_not_restored_state_e7 import _component, _operation
from apps.machines.models import MachineType, ServiceQueue
from apps.makerspaces.models import MakerspaceMembership
from tests.accounts.test_device_auth import attested_login
from tests.test_apiclient_scope_registry import ORIGIN, _signed_headers
from tests.own_requests.own_requests_support import (
    ROUTES, hardware, history_lab, history_url, providers, service,
)

pytestmark = pytest.mark.django_db


def test_browser_origin_cannot_be_retargeted_with_slug_or_client_hints(history_lab, settings):
    lab = history_lab
    settings.PLATFORM_STAFF_ORIGINS = ["https://platform.example.test"]
    for space in (lab.space, lab.other_space):
        space.frontend_domain = f"{space.slug}.example.test"
        space.frontend_domain_status = "verified"
        space.save(update_fields=["frontend_domain", "frontend_domain_status"])
    hardware(lab)
    service(lab, member=lab.user)
    hardware(lab, space=lab.other_space)
    other_type = MachineType.objects.create(makerspace=lab.other_space, slug="mill", name="Mill")
    other_queue = ServiceQueue.objects.create(makerspace=lab.other_space, machine_type=other_type, name="Other queue")
    service(lab, queue=other_queue, member=lab.user)
    origin = {"HTTP_ORIGIN": f"https://{lab.space.frontend_domain}"}
    for route in ROUTES:
        own, foreign = history_url(lab, route), history_url(lab, route, space=lab.other_space)
        assert lab.client.get(own, **origin).status_code == 200
        assert lab.client.get(foreign, **origin).status_code == 403
        assert lab.client.get(foreign, {"makerspace_id": lab.space.pk}, **origin).status_code == 403
        assert lab.client.get(own, {"makerspace": lab.other_space.pk}, **origin).status_code == 403
        assert lab.client.get(own, {"makerspace_id": "invalid"}, **origin).status_code == 403
        assert lab.client.get(own).status_code == 200
        assert lab.client.get(own, HTTP_ORIGIN="https://platform.example.test").status_code == 200
        assert lab.client.get(foreign).data["count"] == 1
        assert lab.client.get(foreign, HTTP_ORIGIN="https://platform.example.test").data["count"] == 1
        assert lab.client.get(reverse(route, args=["missing-history"]), **origin).status_code == 404


@pytest.mark.parametrize("gate", ["module", "archived", "importing", "not_restored"])
def test_history_requires_exact_served_tenant_and_domain_module(history_lab, settings, gate):
    lab = history_lab
    hardware(lab)
    service(lab, member=lab.user)
    if gate == "archived":
        lab.space.archived_at = timezone.now()
        lab.space.save(update_fields=["archived_at"])
    elif gate == "importing":
        lab.space.lifecycle_state = "importing"
        lab.space.save(update_fields=["lifecycle_state"])
    elif gate == "not_restored":
        operation = _operation(makerspace_id=lab.space.pk)
        _component(operation, lab.space.pk)
    if gate == "module":
        # Deliberately malformed legacy JSON: runtime must reject either missing key,
        # even though the operator module editor cannot uninstall core hardware.
        lab.space.enabled_modules = [
            key for key in lab.space.enabled_modules
            if key not in {"request_workflow", "machine_service"}
        ]
        lab.space.save(update_fields=["enabled_modules"])
    for route in ROUTES:
        response = lab.client.get(history_url(lab, route))
        assert response.status_code == (400 if gate == "module" else 404)
        assert "results" not in response.data


def test_native_selection_requires_real_grant_and_current_matching_membership(history_lab, settings, monkeypatch):
    lab = history_lab
    lab.user.set_password("strong-device-password")
    lab.user.save(update_fields=["password"])
    login, _ = attested_login(APIClient(), lab.user, settings, monkeypatch)
    assert login.status_code == 200, login.data
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    for route in ROUTES:
        assert client.get(history_url(lab, route), HTTP_X_MAKERSPACE_ID=str(lab.space.pk)).status_code == 403
    membership = MakerspaceMembership.objects.create(user=lab.user, makerspace=lab.space)
    for route in ROUTES:
        path = history_url(lab, route)
        assert client.get(path, HTTP_X_MAKERSPACE_ID=str(lab.space.pk)).status_code == 200
        assert client.get(path, HTTP_X_MAKERSPACE_ID="invalid").status_code == 403
        assert client.get(history_url(lab, route, space=lab.other_space),
                          HTTP_X_MAKERSPACE_ID=str(lab.space.pk)).status_code == 403
    membership.status = "revoked"
    membership.save(update_fields=["status"])
    for route in ROUTES:
        assert client.get(history_url(lab, route), HTTP_X_MAKERSPACE_ID=str(lab.space.pk)).status_code == 403


def test_actual_registry_requires_public_read_and_exact_target_without_legacy_grant(history_lab, settings):
    lab = history_lab
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/", "/api/v1/public/"]
    assert validate_registry() == ([], [])
    client = ApiClient.objects.create(label="Own history", makerspace=lab.space,
                                      secret_encrypted=b"test", scopes=["public:read"])
    for route in ROUTES:
        for method in ("GET", "HEAD"):
            request = RequestFactory().generic(method, history_url(lab, route))
            request.resolver_match = resolve(request.path_info)
            entry = lookup(request.resolver_match.view_name, method)
            assert entry.target_mode == TARGET_TENANT_SLUG and not entry.legacy_v1
            assert entry.scopes == frozenset({"public:read", "public:*"})
            assert classify(request, client).verdict is True
            client.scopes = [LEGACY_SCOPE]
            assert classify(request, client).verdict is False
            client.scopes = ["public:read"]
        foreign = RequestFactory().get(history_url(lab, route, space=lab.other_space))
        assert classify(foreign, client).verdict is False
        missing = RequestFactory().get(reverse(route, args=["missing-history"]))
        assert classify(missing, client).target_resolved is False


def test_signed_api_client_does_not_replace_the_person_and_cannot_expand_tenant_or_legacy_scope(history_lab, settings):
    lab = history_lab
    settings.API_CLIENT_AUTH_REQUIRED = True
    settings.APICLIENT_REQUIRE_NONCE = False
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/", "/api/v1/public/"]
    api_client, secret = ApiClient.issue(
        label="History transport", makerspace=lab.space, client_type="server",
        allowed_origins=[ORIGIN], scopes=["public:read"],
    )
    for route in ROUTES:
        own = history_url(lab, route)
        headers = _signed_headers(api_client, secret, own)
        # A valid service signature still has no personal request-history identity.
        assert APIClient().get(own, **headers).status_code == 401
        assert lab.client.get(own, **headers).status_code == 200
        foreign = history_url(lab, route, space=lab.other_space)
        assert lab.client.get(foreign, **_signed_headers(api_client, secret, foreign)).status_code == 401
    api_client.scopes = [LEGACY_SCOPE]
    api_client.save(update_fields=["scopes"])
    for route in ROUTES:
        own = history_url(lab, route)
        assert lab.client.get(own, **_signed_headers(api_client, secret, own)).status_code == 401
