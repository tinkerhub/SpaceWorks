"""Real native and OIDC entry points; only external identity-provider I/O is stubbed."""
from types import SimpleNamespace

from django.contrib.messages import get_messages
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import OidcBrowserAttempt
from apps.accounts.transition_services import transition_walk_in_to_account
from apps.audit.models import AuditLog
from tests.accounts.oidc_browser_helpers import ORIGIN, make_provider, metadata, start

from .conftest import NEW_PASSWORD


def native_call(lab):
    return lambda: lab.native.post(reverse("admin:auth_user_password_change", args=[lab.user.pk]),
        {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})


def oidc_call(lab, monkeypatch, *, claims=None, origin=ORIGIN):
    provider = make_provider()
    asserted = {"sub": "claim-source-subject", "email": lab.user.email,
                "email_verified": True, "allow_auto_link": True}
    asserted.update(claims or {})
    monkeypatch.setattr("apps.accounts.views_oidc_browser.discover", lambda _: metadata(provider))
    monkeypatch.setattr("apps.accounts.views_oidc_browser.exchange_code", lambda *a, **kw: "id-token")
    monkeypatch.setattr("apps.accounts.views_oidc_browser.verify_oidc_token", lambda *a, **kw: asserted)
    # Use the shipped email/membership binding. The target deliberately also owns
    # global refresh/device bearers so this transition proves their revocation.
    client = APIClient(HTTP_HOST="testserver")
    if origin == ORIGIN:
        response = start(client, email=lab.user.email, makerspace_slug=lab.spaces[0].slug)
    else:
        response = client.post("/api/v1/auth/social/oidc/campus/authorize",
            {"redirect_uri": f"{origin}/member", "email": lab.user.email,
             "makerspace_slug": lab.spaces[0].slug}, format="json", HTTP_ORIGIN=origin)
    assert response.status_code == 200, response.content
    attempt = OidcBrowserAttempt.objects.latest("pk")
    assert (attempt.intended_user_id, attempt.intended_membership_id) == (
        lab.user.pk, lab.memberships[0].pk)

    def call():
        return APIClient(HTTP_HOST="testserver").post("/api/v1/auth/social/oidc/callback",
            {"code": "code", "state": response.data["state"], "nonce": response.data["nonce"]},
            format="json", HTTP_ORIGIN=origin)

    return SimpleNamespace(call=call, provider=provider, attempt=attempt, claims=asserted)


def prepare(lab, kind, monkeypatch):
    if kind == "native":
        return native_call(lab)
    if kind == "oidc":
        return oidc_call(lab, monkeypatch).call
    if kind == "service":
        return lambda: transition_walk_in_to_account(lab.user, actor=lab.actor)
    raise AssertionError(kind)


def assert_retry(response, kind, *, oidc_status=409):
    if kind == "native":
        assert response.status_code == 302, response.content
        texts = [str(message) for message in get_messages(response.wsgi_request)]
        assert "The account could not be updated right now. Please retry shortly." in texts
        assert "Password changed successfully." not in texts
    else:
        assert response.status_code == oidc_status, response.content
        assert "refresh_token" not in response.cookies
        attempt = OidcBrowserAttempt.objects.get()
        assert attempt.consumed_at is not None
        event = AuditLog.objects.get(action="auth.oidc_browser_attempt_consumed",
                                     target_id=str(attempt.pk))
        assert (event.actor_id, event.makerspace_id, event.target_type, event.meta) == (
            None, None, "accounts.oidcbrowserattempt",
            {"provider": attempt.provider, "outcome": "accepted"})
        failures = AuditLog.objects.filter(action="auth.social_login_failed")
        code = response.json()["code"]
        if code in {"tenant_migration_quiesced", "tenant_migration_gate_unavailable"}:
            assert not failures.exists()
        else:
            assert failures.count() == 1
            event = failures.get()
            assert (event.actor_id, event.makerspace_id, event.meta) == (
                None, None, {"provider": attempt.provider, "reason": code})
