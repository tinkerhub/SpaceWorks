import pytest
from django.contrib.auth import authenticate, get_user_model
from django.test import Client, override_settings
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import DeviceGrant, User
from apps.accounts.tokens import SpaceWorksAccessToken, SpaceWorksRefreshToken
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from tests.accounts.test_device_auth import attested_login
from tests.accounts.test_password_login_surfaces_p3ii import _verified_staff_origin

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
CHANGE_PASSWORD = "/api/v1/auth/change-password"
AUDIT_LOGS = "/api/v1/admin/audit-logs"
CURRENT = "Current-Strong-123"
NEW = "New-Strong-123"


def _user(username="password-user", **kwargs):
    defaults = {
        "password": CURRENT,
        "role": User.Role.SPACE_MANAGER,
        "access_status": User.AccessStatus.ACTIVE,
        "must_change_password": True,
    }
    defaults.update(kwargs)
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@example.com", **defaults
    )


def _login(username, *, origin=None, surface=None):
    client = APIClient()
    data = {"username": username, "password": CURRENT}
    if surface is not None:
        data["surface"] = surface
    response = client.post(
        LOGIN, data, format="json",
        **({"HTTP_ORIGIN": origin} if origin else {}),
    )
    assert response.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return client, response


def _change(client, current=CURRENT, new=NEW, **headers):
    return client.post(
        CHANGE_PASSWORD,
        {"current_password": current, "new_password": new},
        format="json", **headers,
    )


def _refresh(token, settings, origin="http://localhost:5000"):
    client = APIClient()
    client.cookies[settings.AUTH_REFRESH_COOKIE] = token
    header = f"HTTP_{settings.AUTH_REFRESH_CSRF_HEADER.upper().replace('-', '_')}"
    return client.post(
        "/api/v1/auth/refresh", format="json", HTTP_ORIGIN=origin, **{header: "1"},
    )


def test_must_change_password_blocks_protected_api_until_rotated():
    """A temporary password must not reach protected staff endpoints over the
    API before rotating — only the rotation/me path stays open."""
    _user("gated-superadmin", role=User.Role.SUPERADMIN, is_staff=True, is_superuser=True)
    client, _ = _login("gated-superadmin")

    blocked = client.get(AUDIT_LOGS)
    assert blocked.status_code == 403  # protected surface is closed pre-rotation

    rotated = _change(client)
    assert rotated.status_code == 200  # rotation path stayed open

    allowed = client.get(AUDIT_LOGS)
    assert allowed.status_code == 200  # flag cleared, surface reopens


def test_must_change_password_blocks_django_admin():
    """A temporary password must not reach /admin/ before rotating, or it would
    bypass the API/staff-console forced-change gate."""
    user = _user("admin-gated-super", role=User.Role.SUPERADMIN, is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)

    blocked = client.get("/control/")
    assert blocked.status_code == 403

    user.must_change_password = False
    user.save(update_fields=["must_change_password"])
    client.force_login(user)
    assert client.get("/control/").status_code == 200


def test_change_password_blacklists_outstanding_refresh_tokens(settings):
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

    user = _user("rotate-blacklist")
    space, _ = _verified_staff_origin("rotate-blacklist")
    MakerspaceMembership.objects.create(user=user, makerspace=space,
                                       role=MakerspaceMembership.Role.SPACE_MANAGER)
    client, login = _login("rotate-blacklist")
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5000"]
    assert SpaceWorksAccessToken(login.data["access"])["surface"] == "staff_api"
    old_refresh = login.cookies[settings.AUTH_REFRESH_COOKIE].value
    before = BlacklistedToken.objects.count()
    changed = _change(client)
    assert changed.status_code == 200
    assert changed.data["access"]
    assert SpaceWorksAccessToken(changed.data["access"])["surface"] == "staff_api"
    assert BlacklistedToken.objects.count() > before  # pre-rotation session revoked
    new_refresh = changed.cookies[settings.AUTH_REFRESH_COOKIE].value
    assert new_refresh != old_refresh
    assert _refresh(new_refresh, settings).status_code == 200
    assert _refresh(old_refresh, settings).status_code == 401


def test_login_and_me_include_must_change_password():
    _user("must-change")
    client, login = _login("must-change")
    me = client.get(ME)

    assert login.status_code == 200
    assert login.data["user"]["must_change_password"] is True
    assert me.status_code == 200
    assert me.data["must_change_password"] is True


def test_change_password_validates_updates_and_audits():
    user = _user("password-user")
    client, _ = _login("password-user")

    for current, new, field in [("wrong", NEW, "current_password"),
                                (CURRENT, CURRENT, "new_password"),
                                (CURRENT, "short", "new_password")]:
        invalid = _change(client, current, new)
        assert invalid.status_code == 400
        assert field in invalid.data
    changed = _change(client)
    assert changed.status_code == 200
    assert changed.data["detail"] == "Password updated."
    assert changed.data["access"]

    user.refresh_from_db()
    assert user.must_change_password is False
    assert authenticate(username="password-user", password="New-Strong-123") == user
    assert AuditLog.objects.filter(
        actor=user,
        action="user.password_changed",
        target_type="accounts.user",
        target_id=str(user.id),
    ).exists()


def test_staff_session_reissue_preserves_origin_scope(settings):
    space, origin = _verified_staff_origin("change-staff")
    _, other_origin = _verified_staff_origin("change-other")
    user = _user(must_change_password=False)
    MakerspaceMembership.objects.create(user=user, makerspace=space,
                                       role=MakerspaceMembership.Role.SPACE_MANAGER)
    client, _ = _login(user.username, origin=origin, surface="staff")
    changed = _change(client, HTTP_ORIGIN=origin)
    assert changed.status_code == 200
    refresh = changed.cookies[settings.AUTH_REFRESH_COOKIE].value
    for claims in (SpaceWorksAccessToken(changed.data["access"]), SpaceWorksRefreshToken(refresh)):
        assert claims["surface"] == "staff"
        assert claims["staff_scope"] == str(space.pk)
    assert _refresh(refresh, settings, other_origin).status_code == 403
    assert _refresh(refresh, settings, origin).status_code == 200


@pytest.mark.parametrize("surface", ["member", None])
def test_member_and_legacy_session_reissue_preserves_surface(surface, settings):
    user = _user(role=User.Role.REQUESTER)
    client = APIClient()
    if surface is None:
        refresh = SpaceWorksRefreshToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    else:
        client, _ = _login(user.username, surface=surface)
    changed = _change(client)
    assert changed.status_code == 200
    for claims in (SpaceWorksAccessToken(changed.data["access"]),
                   SpaceWorksRefreshToken(changed.cookies[settings.AUTH_REFRESH_COOKIE].value)):
        assert claims.get("surface") == surface
        if surface is None:
            assert "surface" not in claims
        assert "staff_scope" not in claims


def test_native_password_change_revokes_grant_without_browser_session(settings, monkeypatch):
    user = _user(role=User.Role.REQUESTER, must_change_password=False)
    client = APIClient()
    login, _ = attested_login(client, user, settings, monkeypatch, password=CURRENT)
    assert login.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    changed = _change(client)
    assert changed.status_code == 200
    assert changed.data == {"detail": "Password updated."}
    assert not changed.cookies
    grant = DeviceGrant.objects.get(pk=login.data["device_grant"]["id"])
    assert grant.status == DeviceGrant.Status.REVOKED
    assert not grant.refresh_families.filter(revoked_at__isnull=True).exists()
    assert client.get(ME).status_code == 401


def test_unusable_password_returns_password_not_set():
    user = _user(password=None)
    client = APIClient()
    refresh = SpaceWorksRefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    response = _change(client)
    assert response.status_code == 400
    error = response.data["current_password"]
    assert error.code == "password_not_set"
    assert str(error) == "This account has no password yet. Use “Forgot password” on the sign-in page to set one."


def test_password_change_preserves_leading_and_trailing_whitespace():
    user = _user()
    client, _ = _login(user.username)
    user.set_password(" pass word 12 ")
    user.save(update_fields=["password"])
    response = _change(client, " pass word 12 ", " replacement pass word 34 ")
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password(" replacement pass word 34 ")
    assert not user.check_password("replacement pass word 34")


def test_change_password_throttles_sixth_attempt(settings, monkeypatch):
    rates = {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "change_password": "5/min"}
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", rates)
    with override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK,
                                         "DEFAULT_THROTTLE_RATES": rates}):
        client, _ = _login(_user().username)
        for _ in range(5):
            assert _change(client, current="wrong").status_code == 400
        response = _change(client, current="wrong")
    assert response.status_code == 429
    assert "Retry-After" in response


@pytest.mark.parametrize("superadmin", [False, True])
def test_admin_password_reset_rejects_self_target(superadmin):
    user = _user(role=User.Role.SUPERADMIN if superadmin else User.Role.SPACE_MANAGER,
                 is_superuser=superadmin, is_staff=superadmin, must_change_password=False)
    space, _ = _verified_staff_origin("self-reset")
    MakerspaceMembership.objects.create(user=user, makerspace=space,
                                       role=MakerspaceMembership.Role.SPACE_MANAGER)
    client, _ = _login(user.username)
    response = client.post(f"/api/v1/admin/users/{user.pk}/reset-password", format="json")
    assert response.status_code == 400
    assert str(response.data["detail"]) == "Use Change password to change your own password."
    user.refresh_from_db()
    assert user.check_password(CURRENT)
    assert user.must_change_password is False
    assert not AuditLog.objects.filter(action="user.password_reset", target_id=str(user.pk)).exists()
