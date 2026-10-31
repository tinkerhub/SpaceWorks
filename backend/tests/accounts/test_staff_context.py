"""Browser discovery must describe validated authority, never infer portal trust."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace
from tests.return_helpers import make_member, make_space, make_user

pytestmark = pytest.mark.django_db
ORIGIN = "https://shared.example.test"
PASSWORD = "staff-context-test-password"


@pytest.fixture(autouse=True)
def portal(settings):
    settings.PLATFORM_STAFF_ORIGINS = [ORIGIN]
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]
    settings.PLATFORM_DOMAIN_SUFFIX = ""


def global_user(**extra):
    return make_user(
        "context-root", role=User.Role.SUPERADMIN, is_superuser=True,
        access_status=User.AccessStatus.ACTIVE, password=PASSWORD, **extra,
    )


def login(user, *, origin=ORIGIN, surface="staff"):
    data = {"username": user.username, "password": PASSWORD}
    if surface is not None:
        data["surface"] = surface
    return APIClient().post(
        "/api/v1/auth/login", data, format="json",
        HTTP_HOST="testserver",
        **({"HTTP_ORIGIN": origin} if origin else {}),
    )


def me(access, *, origin=ORIGIN):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client.get("/api/v1/auth/me", HTTP_ORIGIN=origin, HTTP_HOST="testserver")


@pytest.mark.parametrize("surface", ["staff", None])
def test_effective_password_staff_session_discovers_platform_without_any_spaces(surface):
    user = global_user()
    assert not Makerspace.objects.exists()
    issued = login(user, surface=surface)
    assert issued.status_code == 200, issued.data
    assert issued.data["surface"] == "staff"
    expected = {
        "scope_kind": "platform", "makerspace_id": None,
        "can_manage_platform": True, "platform_hosting": False,
        "platform_stripe_connect_available": False,
    }
    assert issued.data["user"]["staff_context"] == expected
    current = me(issued.data["access"])
    assert current.status_code == 200, current.data
    assert current.data["staff_context"] == expected
    assert current.data["makerspaces"] == []


def test_verified_dedicated_origin_returns_only_its_context_without_global_grants():
    space = make_space("context-dedicated")
    space.frontend_domain = "dedicated.example.test"
    space.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    space.save(update_fields=["frontend_domain", "frontend_domain_status"])
    user = global_user()
    # Dedicated staff issuance requires real authority in this makerspace.
    from apps.makerspaces.models import MakerspaceMembership

    MakerspaceMembership.objects.create(user=user, makerspace=space, role="space_manager")
    issued = login(user, origin="https://dedicated.example.test")
    assert issued.status_code == 200, issued.data
    context = issued.data["user"]["staff_context"]
    assert context["scope_kind"] == "makerspace"
    assert context["makerspace_id"] == space.pk
    assert context["can_manage_platform"] is False
    assert me(issued.data["access"], origin="https://dedicated.example.test").data["staff_context"] == context


@pytest.mark.parametrize("registered_for_cors", [False, True])
def test_unregistered_staff_origin_never_becomes_platform_from_no_scope(settings, registered_for_cors):
    origin = "https://public-only.example.test"
    settings.PUBLIC_APP_BASE_URL = origin
    if registered_for_cors:
        settings.CORS_ALLOWED_ORIGINS = [ORIGIN, origin]
    issued = login(global_user(), origin=origin)
    assert issued.status_code == 200, issued.data
    assert issued.data["surface"] == "staff_api"
    assert "staff_context" not in issued.data["user"]
    current = me(issued.data["access"], origin=origin)
    assert current.status_code == 200, current.data
    assert "staff_context" not in current.data


def test_browser_staff_token_cannot_discover_context_from_a_cors_only_origin(settings):
    issued = login(global_user())
    assert issued.status_code == 200, issued.data
    public_origin = "https://cors-only.example.test"
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN, public_origin]
    denied = me(issued.data["access"], origin=public_origin)
    assert denied.status_code == 403, denied.data
    assert "staff_context" not in denied.data


def test_ordinary_staff_on_platform_origin_has_no_global_capability():
    user = make_member("context-manager", make_space("context-manager"))
    user.set_password(PASSWORD)
    user.save(update_fields=["password"])
    issued = login(user)
    assert issued.status_code == 200, issued.data
    assert issued.data["user"]["staff_context"]["can_manage_platform"] is False
    assert me(issued.data["access"]).data["staff_context"]["can_manage_platform"] is False


@pytest.mark.parametrize("surface,origin", [("member", ORIGIN), (None, "")])
def test_global_identity_on_member_or_staff_api_surface_omits_context(surface, origin):
    issued = login(global_user(), surface=surface, origin=origin)
    assert issued.status_code == 200, issued.data
    assert issued.data["surface"] == ("member" if surface else "staff_api")
    assert "staff_context" not in issued.data["user"]
    current = me(issued.data["access"])
    assert current.status_code == 200, current.data
    assert "staff_context" not in current.data


def test_unverified_global_password_identity_has_verification_surface_without_context():
    user = global_user(self_registered_at=timezone.now())
    issued = login(user)
    assert issued.status_code == 200, issued.data
    assert issued.data["surface"] == "verification_only"
    assert "staff_context" not in issued.data["user"]
    current = me(issued.data["access"])
    assert current.status_code == 200, current.data
    assert "staff_context" not in current.data


def test_password_rotation_gate_withholds_global_capability():
    issued = login(global_user(must_change_password=True))
    assert issued.status_code == 200, issued.data
    assert issued.data["user"]["staff_context"]["can_manage_platform"] is False
    current = me(issued.data["access"])
    assert current.status_code == 200, current.data
    assert current.data["staff_context"]["can_manage_platform"] is False


@pytest.mark.parametrize("status", [User.AccessStatus.RESTRICTED, User.AccessStatus.SUSPENDED])
def test_restricted_global_identity_cannot_issue_platform_context(status):
    user = global_user()
    previous = login(user)
    assert previous.status_code == 200, previous.data
    user.access_status = status
    user.save(update_fields=["access_status"])
    denied = login(user)
    assert denied.status_code in (401, 403)
    assert "user" not in denied.data
    current = me(previous.data["access"])
    if current.status_code == 200:
        assert current.data["staff_context"]["can_manage_platform"] is False
    else:
        assert current.status_code in (401, 403)


@pytest.mark.parametrize("payments_active", [True, False])
def test_managed_host_stripe_capability_requires_payments_runtime_even_without_spaces(settings, monkeypatch, payments_active):
    from apps.separability import registry

    settings.PLATFORM_DOMAIN_SUFFIX = "example.test"
    settings.INFRA_HOSTS = {"testserver"}
    # Model the deployment runtime, without importing payments services.
    monkeypatch.setitem(registry._runtime_apps._entries, "payments", payments_active)
    assert not Makerspace.objects.exists()
    issued = login(global_user())
    assert issued.status_code == 200, issued.data
    context = issued.data["user"]["staff_context"]
    assert context["can_manage_platform"] is True
    assert context["platform_hosting"] is True
    assert context["platform_stripe_connect_available"] is payments_active
