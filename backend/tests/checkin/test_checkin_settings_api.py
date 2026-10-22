"""The console's Check-in settings: who may edit, what is refused, and the test button."""

import hashlib

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.checkin.roster_fakes import (
    PUBLIC_IP,
    FakeResponse,
    fake_dns,
    fake_upstream,
    roster_body,
    row,
)
from tests.return_helpers import make_member

pytestmark = pytest.mark.django_db

CORE = ["public_inventory", "request_workflow", "staff_admin"]
ROSTER = "https://roster.example.net/active"


@pytest.fixture(autouse=True)
def _no_deployment_roster(settings, monkeypatch):
    settings.CHECKIN_API_URL = ""
    settings.CHECKIN_REQUIRED_PURPOSE = "Working on a project"
    settings.CHECKIN_PROVIDER_NAME = ""
    fake_dns(monkeypatch, {
        "roster.example.net": [PUBLIC_IP],
        "inside.example.net": ["10.1.2.3"],
        "localhost": ["127.0.0.1"],
    })


def _space(slug, **extra):
    extra.setdefault("enabled_modules", list(CORE))
    return Makerspace.objects.create(name=slug, slug=slug, **extra)


def _url(space, suffix=""):
    return f"/api/v1/admin/makerspaces/{space.pk}/checkin-settings{suffix}"


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _manager(space, name="sm"):
    return make_member(f"{space.slug}-{name}", space)


def _inventory_manager(space):
    return make_member(
        f"{space.slug}-im", space,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )


# --- permissions --------------------------------------------------------------


def test_space_manager_reads_and_saves_with_an_audit_entry():
    space = _space("cs-sm")
    client = _client(_manager(space))

    response = client.patch(_url(space), {
        "checkin_api_url": ROSTER,
        "checkin_required_purpose": "Tinkering",
        "checkin_provider_name": "Space Pass",
        "checkin_space_id": 4,
    }, format="json")

    assert response.status_code == 200, response.data
    space.refresh_from_db()
    assert (space.checkin_api_url, space.checkin_required_purpose) == (ROSTER, "Tinkering")
    assert (space.checkin_provider_name, space.checkin_space_id) == ("Space Pass", 4)
    assert response.data["effective"] == {
        "api_url_source": "makerspace",
        "required_purpose": "Tinkering",
        "provider_name": "Space Pass",
    }
    entry = AuditLog.objects.get(action="checkin.settings_updated", makerspace=space)
    assert entry.meta["fields"] == [
        "checkin_api_url", "checkin_provider_name", "checkin_required_purpose", "checkin_space_id"
    ]
    assert ROSTER not in str(entry.meta)
    assert client.get(_url(space)).data["checkin_api_url"] == ROSTER


def test_inventory_manager_may_read_but_not_save_or_test():
    space = _space("cs-im")
    client = _client(_inventory_manager(space))

    assert client.get(_url(space)).status_code == 200
    assert client.patch(_url(space), {"checkin_provider_name": "X"}, format="json").status_code == 404
    assert client.post(_url(space, "/test"), {}, format="json").status_code == 404
    space.refresh_from_db()
    assert space.checkin_provider_name == ""


def test_another_makerspaces_space_manager_cannot_see_or_edit():
    space = _space("cs-target")
    other = _space("cs-other")
    client = _client(_manager(other))

    assert client.get(_url(space)).status_code == 404
    assert client.patch(_url(space), {"checkin_provider_name": "X"}, format="json").status_code == 404


def test_superadmin_may_edit():
    space = _space("cs-super")
    admin = User.objects.create_user(
        username="cs-superadmin", email="cs-superadmin@example.test", role=User.Role.SUPERADMIN,
        is_staff=True, is_superuser=True, access_status=User.AccessStatus.ACTIVE,
    )
    response = _client(admin).patch(_url(space), {"checkin_provider_name": "Pass"}, format="json")
    assert response.status_code == 200, response.data


def test_a_tenant_origin_cannot_reach_another_tenants_settings():
    home = _space("cs-home", frontend_domain="cs-home.example.test",
                  frontend_domain_status=Makerspace.DomainStatus.VERIFIED)
    other = _space("cs-away", frontend_domain="cs-away.example.test",
                   frontend_domain_status=Makerspace.DomainStatus.VERIFIED)
    user = _manager(home)
    MakerspaceMembership.objects.create(
        user=user, makerspace=other, role=MakerspaceMembership.Role.SPACE_MANAGER
    )
    client = _client(user)
    origin = {"HTTP_ORIGIN": "https://cs-home.example.test"}

    assert client.get(_url(home), **origin).status_code == 200
    assert client.get(_url(other), **origin).status_code == 403
    assert client.patch(_url(other), {"checkin_provider_name": "X"}, format="json",
                        **origin).status_code == 403


# --- save-time validation -------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/active",
    "https://localhost/active",
    "https://169.254.169.254/latest/meta-data",
    "https://inside.example.net/active",
    "http://roster.example.net/active",
    "https://user:pw@roster.example.net/active",
])
def test_unsafe_roster_urls_are_refused_on_save(url):
    space = _space(f"cs-unsafe-{hashlib.sha256(url.encode()).hexdigest()[:10]}")
    response = _client(_manager(space)).patch(
        _url(space), {"checkin_api_url": url}, format="json"
    )
    assert response.status_code == 400
    assert "checkin_api_url" in response.data
    space.refresh_from_db()
    assert space.checkin_api_url == ""


def test_switching_to_checked_in_needs_a_roster_and_a_space_id():
    space = _space("cs-mode")
    client = _client(_manager(space))

    no_roster = client.patch(_url(space), {
        "public_request_mode": "checked_in", "checkin_space_id": 3,
    }, format="json")
    no_space = client.patch(_url(space), {
        "public_request_mode": "checked_in", "checkin_api_url": ROSTER,
    }, format="json")
    both = client.patch(_url(space), {
        "public_request_mode": "checked_in", "checkin_api_url": ROSTER, "checkin_space_id": 3,
    }, format="json")

    assert no_roster.status_code == 400 and "checkin_api_url" in no_roster.data
    assert no_space.status_code == 400 and "checkin_space_id" in no_space.data
    assert both.status_code == 200, both.data
    assert both.data["request_access"] == "checked_in"
    assert AuditLog.objects.filter(
        action="makerspace.request_access_changed", makerspace=space
    ).exists()


def test_leaving_checked_in_may_clear_the_binding_in_the_same_save():
    space = _space("cs-leave", public_request_mode="checked_in", checkin_space_id=3,
                   checkin_api_url=ROSTER)
    response = _client(_manager(space)).patch(_url(space), {
        "public_request_mode": "disabled", "checkin_space_id": None, "checkin_api_url": "",
    }, format="json")

    assert response.status_code == 200, response.data
    space.refresh_from_db()
    assert (space.public_request_mode, space.checkin_space_id) == ("disabled", None)


def test_membership_still_wins_over_the_console():
    space = _space("cs-member", enabled_modules=[*CORE, "membership"])
    response = _client(_manager(space)).patch(_url(space), {
        "public_request_mode": "checked_in", "checkin_api_url": ROSTER, "checkin_space_id": 3,
    }, format="json")

    assert response.status_code == 400
    assert "public_request_mode" in response.data
    space.refresh_from_db()
    assert space.public_request_mode == "disabled"
    assert space.checkin_api_url == ""  # the whole save rolled back


# --- test connection ------------------------------------------------------------


@pytest.mark.parametrize("outcome, code", [
    (FakeResponse(body=b"<html>busy</html>"), "not_json"),
    (FakeResponse(body=b'{"rows": []}'), "not_array"),
    (FakeResponse(status=500, body=b"secret stack trace"), "http_status"),
    (TimeoutError(), "timeout"),
    (ConnectionRefusedError(), "unreachable"),
])
def test_test_connection_explains_failures_without_echoing_the_body(monkeypatch, outcome, code):
    space = _space(f"cs-test-{code}")
    fake_upstream(monkeypatch, {"roster.example.net": outcome})

    response = _client(_manager(space)).post(
        _url(space, "/test"), {"checkin_api_url": ROSTER}, format="json"
    )

    assert response.status_code == 200
    assert response.data["ok"] is False
    assert response.data["code"] == code
    assert response.data["reason"]
    assert "busy" not in str(response.data) and "secret" not in str(response.data)


def test_test_connection_refuses_a_private_candidate_without_connecting(monkeypatch):
    space = _space("cs-test-private")
    calls = fake_upstream(monkeypatch, {})

    response = _client(_manager(space)).post(
        _url(space, "/test"), {"checkin_api_url": "https://inside.example.net/x"}, format="json"
    )

    assert response.data["ok"] is False
    assert response.data["code"] == "refused_address"
    assert calls == []


def test_test_connection_counts_rows_for_the_saved_roster(monkeypatch):
    space = _space("cs-test-ok", checkin_api_url=ROSTER, checkin_space_id=1)
    fake_upstream(monkeypatch, {
        "roster.example.net": FakeResponse(body=roster_body(row(mid=1), row(mid=2, space_id=9))),
    })

    response = _client(_manager(space)).post(_url(space, "/test"), {}, format="json")

    assert response.data == {"ok": True, "rows": 2, "space_rows": 1, "code": "", "reason": ""}


def test_test_connection_with_nothing_configured_says_so():
    space = _space("cs-test-none")
    response = _client(_manager(space)).post(_url(space, "/test"), {}, format="json")
    assert response.data["ok"] is False
    assert response.data["code"] == "not_configured"


# --- the CLI writer ---------------------------------------------------------------


def test_set_request_access_accepts_a_per_makerspace_roster():
    space = _space("cs-cli")
    call_command(
        "set_request_access", "--makerspace", space.slug, "--mode", "checked_in",
        "--checkin-space-id", "5", "--checkin-api-url", ROSTER,
        "--checkin-purpose", "Tinkering", "--checkin-provider-name", "Space Pass",
    )
    space.refresh_from_db()
    assert space.public_request_mode == "checked_in"
    assert (space.checkin_api_url, space.checkin_required_purpose) == (ROSTER, "Tinkering")
    assert space.checkin_provider_name == "Space Pass"


def test_set_request_access_refuses_a_private_roster_and_changes_nothing():
    space = _space("cs-cli-private")
    with pytest.raises(CommandError, match="checkin-api-url"):
        call_command(
            "set_request_access", "--makerspace", space.slug, "--mode", "checked_in",
            "--checkin-space-id", "5", "--checkin-api-url", "https://169.254.169.254/x",
        )
    space.refresh_from_db()
    assert (space.public_request_mode, space.checkin_space_id) == ("disabled", None)
