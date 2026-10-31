"""Authentication refusals use real accounts, JWTs and the existing claim harness."""

from unittest.mock import Mock

import pytest
from django.urls import resolve
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIClient
from apps.accounts.tokens import SpaceWorksRefreshToken

from apps.accounts.claim_route_guard import validate_claim_route_matrix
from apps.accounts.claim_route_types import AnonymousRead, Refused
from apps.accounts.claim_routes import policy_for
from tests.accounts.claim_helpers_p7 import redeemed_claim
from tests.own_requests.own_requests_support import (
    ROUTES, hardware, history_lab, history_url, providers, service,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("route", ROUTES)
def test_anonymous_history_is_not_a_public_identity_lookup(history_lab, route):
    lab = history_lab
    hardware(lab)
    service(lab, member=lab.user)
    response = APIClient().get(history_url(lab, route), {"email": lab.user.email})
    assert response.status_code == 401
    assert "results" not in response.data
    # Inspect the actual resolved view, not an alternate test URLconf.
    assert resolve(history_url(lab, route)).func.cls.permission_classes == [IsAuthenticated]


@pytest.mark.parametrize("changes", [
    {"is_active": False}, {"access_status": "restricted"},
    {"access_status": "suspended"}, {"must_change_password": True},
    {"is_walk_in": True}, {"is_tenant_dump_stub": True},
])
def test_shared_account_helper_refuses_unfit_principals_on_both_lists(history_lab, changes):
    lab = history_lab
    hardware(lab)
    service(lab, member=lab.user)
    for key, value in changes.items():
        setattr(lab.user, key, value)
    lab.user.save(update_fields=list(changes))
    # Force authentication deliberately reaches the handler's real-account check,
    # including inactive/stub accounts normally rejected even earlier by JWT auth.
    for route in ROUTES:
        response = lab.client.get(history_url(lab, route))
        assert response.status_code == 403 and "results" not in response.data


def test_another_tenants_shared_anonymous_sentinel_never_owns_history(history_lab):
    lab = history_lab
    hardware(lab)
    service(lab, member=lab.user)
    lab.other_space.anonymous_requester = lab.user
    lab.other_space.save(update_fields=["anonymous_requester"])
    for route in ROUTES:
        response = lab.client.get(history_url(lab, route))
        assert response.status_code == 403 and "results" not in response.data


def test_browser_jwt_reads_without_membership_but_cannot_claim_native_header(history_lab):
    lab = history_lab
    hardware(lab)
    service(lab, member=lab.user)
    token = SpaceWorksRefreshToken.for_user(lab.user)
    token["surface"] = "member"
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    for route in ROUTES:
        path = history_url(lab, route)
        response = client.get(path)
        assert response.status_code == 200 and response.data["count"] == 1
        assert client.get(path, HTTP_X_MAKERSPACE_ID=str(lab.space.pk)).status_code == 403


def test_authenticated_history_does_not_fetch_a_current_checked_in_roster(history_lab, monkeypatch):
    from apps.makerspaces.request_access import MODE_CHECKED_IN

    lab = history_lab
    lab.space.public_request_mode = MODE_CHECKED_IN
    lab.space.checkin_space_id = 23
    lab.space.checkin_api_url = "https://roster.invalid/unavailable"
    lab.space.save(update_fields=["public_request_mode", "checkin_space_id", "checkin_api_url"])
    roster = Mock(side_effect=AssertionError("History must not fetch the roster"))
    monkeypatch.setattr("apps.checkin.client.fetch_roster", roster)
    hardware(lab)
    service(lab, member=lab.user)
    for route in ROUTES:
        response = lab.client.get(history_url(lab, route))
        assert response.status_code == 200 and response.data["count"] == 1
    roster.assert_not_called()


def test_real_claim_session_is_refused_for_get_and_head_on_both_routes(settings):
    settings.MEMBER_CLAIM_SESSION_TTL_SECONDS = 600
    harness = redeemed_claim("own-history")
    # A successful authenticated claim call proves this is a live session.
    assert harness.claim_client.get("/api/v1/auth/me").status_code == 200
    for route in ROUTES:
        from django.urls import reverse

        path = reverse(route, args=[harness.space.slug])
        assert isinstance(policy_for(route, "OPTIONS"), AnonymousRead)
        for method in ("GET", "HEAD"):
            assert isinstance(policy_for(route, method), Refused)
            response = harness.claim_client.generic(method, path)
            assert response.status_code == 403
    # Runs actual URL introspection and the framework pre-auth guard.
    validated = validate_claim_route_matrix()
    assert validated
