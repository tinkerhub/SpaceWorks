"""Use real nonce/session flows; replace only the upstream identity assertion."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models_social import PlatformSocialAuthSettings
from tests.accounts.oidc_browser_helpers import make_provider, metadata
from tests.accounts.test_staff_context import ORIGIN, global_user, me

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def portal(settings):
    settings.PLATFORM_STAFF_ORIGINS = [ORIGIN]
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]


@pytest.mark.parametrize("provider", ["google", "oidc:campus"])
@pytest.mark.parametrize("surface", ["staff", "member"])
def test_social_web_context_follows_validated_surface_even_for_global_identity(monkeypatch, provider, surface):
    user = global_user(email_verified_at=timezone.now())
    if provider == "google":
        config = PlatformSocialAuthSettings.load()
        config.google_web_client_id = "context-google-client"
        config.save()
        path = "/api/v1/auth/social/google"
    else:
        make_provider()
        path = "/api/v1/auth/social/oidc/campus"
    monkeypatch.setattr("apps.accounts.views_social._verify", lambda *a, **k: {
        "sub": "context-sub", "email": user.email, "email_verified": True,
    })
    client = APIClient()
    challenge = client.post("/api/v1/auth/social/nonce", {
        "provider": provider, "surface": surface, "delivery": "web", "client_platform": "web",
    }, format="json", HTTP_ORIGIN=ORIGIN)
    assert challenge.status_code == 200, challenge.data
    issued = client.post(path, {
        "id_token": "upstream-token", "nonce": challenge.data["nonce"],
        "surface": surface, "delivery": "web", "client_platform": "web",
    }, format="json", HTTP_ORIGIN=ORIGIN)
    assert issued.status_code == 200, issued.data
    assert issued.data["user"]["id"] == user.pk
    current = me(issued.data["access"])
    assert current.status_code == 200, current.data
    if surface == "staff":
        assert issued.data["user"]["staff_context"]["can_manage_platform"] is True
        assert current.data["staff_context"] == issued.data["user"]["staff_context"]
    else:
        assert "staff_context" not in issued.data["user"]
        assert "staff_context" not in current.data


def test_member_only_oidc_code_callback_does_not_promote_a_global_identity(monkeypatch):
    user = global_user(email_verified_at=timezone.now())
    provider = make_provider()
    monkeypatch.setattr("apps.accounts.views_oidc_browser.discover", lambda _: metadata(provider))
    monkeypatch.setattr("apps.accounts.views_oidc_browser.exchange_code", lambda *a, **k: "upstream-token")
    monkeypatch.setattr("apps.accounts.views_oidc_browser.verify_oidc_token", lambda *a, **k: {
        "sub": "context-code-sub", "email": user.email, "email_verified": True,
    })
    client = APIClient()
    started = client.post("/api/v1/auth/social/oidc/campus/authorize", {
        "redirect_uri": f"{ORIGIN}/member",
    }, format="json", HTTP_ORIGIN=ORIGIN)
    assert started.status_code == 200, started.data
    issued = client.post("/api/v1/auth/social/oidc/callback", {
        "code": "valid-code", "state": started.data["state"], "nonce": started.data["nonce"],
    }, format="json", HTTP_ORIGIN=ORIGIN)
    assert issued.status_code == 200, issued.data
    assert issued.data["user"]["id"] == user.pk
    assert "staff_context" not in issued.data["user"]
    current = me(issued.data["access"])
    assert current.status_code == 200, current.data
    assert "staff_context" not in current.data


def test_claim_identity_never_advertises_staff_context():
    from tests.accounts.claim_helpers_p7 import redeemed_claim

    claim = redeemed_claim("staff-context")
    current = claim.claim_client.get("/api/v1/auth/me", HTTP_ORIGIN=ORIGIN)
    assert current.status_code == 200, current.data
    assert "staff_context" not in current.data


def test_attested_native_social_session_for_global_identity_has_no_browser_context(monkeypatch):
    from apps.accounts.models import DeviceGrant
    from apps.accounts.services_device_tokens import issue_device_token_pair
    from tests.device_helpers import make_native_app_registration

    user = global_user(email_verified_at=timezone.now())
    config = PlatformSocialAuthSettings.load()
    config.google_ios_client_id = "context-google-ios"
    config.google_web_client_id = "context-google-web"
    config.save()
    now = timezone.now()
    grant = DeviceGrant.objects.create(
        registration=make_native_app_registration(), user=user, platform="apple",
        app_id="org.spaceworks.app", signing_identity="TEAM.org.spaceworks.app",
        environment="development", attestation_subject_fingerprint="f" * 64,
        attested_at=now, last_used_at=now,
    )
    access, _, _ = issue_device_token_pair(user, grant)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    monkeypatch.setattr("apps.accounts.views_social._verify", lambda *a, **k: {
        "sub": "context-device", "email": user.email, "email_verified": True,
    })
    challenge = client.post("/api/v1/auth/social/nonce", {
        "provider": "google", "surface": "member", "delivery": "device", "client_platform": "ios",
    }, format="json")
    assert challenge.status_code == 200, challenge.data
    issued = client.post("/api/v1/auth/social/google", {
        "nonce": challenge.data["nonce"], "id_token": "device-token",
        "surface": "member", "delivery": "device", "client_platform": "ios",
    }, format="json")
    assert issued.status_code == 200, issued.data
    assert "staff_context" not in issued.data["user"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.data['access']}")
    current = client.get("/api/v1/auth/me")
    assert current.status_code == 200, current.data
    assert "staff_context" not in current.data


def test_auth_schema_declares_context_optional_with_nullable_scope_id():
    from apps.accounts.schemas_auth import UserPayloadSerializer

    field = UserPayloadSerializer.fields["staff_context"]
    assert field.required is False
    assert field.fields["makerspace_id"].allow_null is True
