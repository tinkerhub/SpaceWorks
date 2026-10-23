"""Per-makerspace rosters: no cross-tenant cache leakage, and the SSRF guard at fetch time."""

import hashlib

import pytest
import requests
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.checkin import client, transport
from apps.checkin.client import CheckinUnavailable
from apps.makerspaces.models import Makerspace
from apps.makerspaces.request_access import MODE_CHECKED_IN
from tests.checkin.roster_fakes import (
    PUBLIC_IP,
    FakeResponse,
    fake_dns,
    fake_upstream,
    roster_body,
    row,
)

pytestmark = pytest.mark.django_db

CORE = ["public_inventory", "request_workflow", "staff_admin"]
URL_A = "https://roster-a.example.net/active"
URL_B = "https://roster-b.example.net/active"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def _space(slug, url="", space_id=1):
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=list(CORE),
        public_request_mode=MODE_CHECKED_IN, checkin_space_id=space_id,
        checkin_api_url=url,
    )


def _lookup(space, name):
    return APIClient().post(
        reverse("checkin:lookup", args=[space.slug]), {"name": name}, format="json"
    )


# --- isolation ----------------------------------------------------------------


def test_cached_rosters_are_keyed_by_url_not_shared(monkeypatch, settings):
    settings.CHECKIN_API_URL = ""
    a = _space("iso-a", URL_A)
    b = _space("iso-b", URL_B)
    fake_dns(monkeypatch, {"roster-a.example.net": [PUBLIC_IP], "roster-b.example.net": [PUBLIC_IP]})
    calls = fake_upstream(monkeypatch, {
        "roster-a.example.net": FakeResponse(body=roster_body(row(mid=1, name="Ada A"))),
        "roster-b.example.net": FakeResponse(body=roster_body(row(mid=2, name="Bea B"))),
    })

    assert [e.mid for e in client.fetch_roster(a, cached=True)] == [1]
    assert [e.mid for e in client.fetch_roster(b, cached=True)] == [2]
    assert [e.mid for e in client.fetch_roster(a, cached=True)] == [1]
    assert [host for host, _ip, _path in calls] == ["roster-a.example.net", "roster-b.example.net"]


def test_lookup_on_one_makerspace_never_sees_anothers_roster(monkeypatch, settings):
    """Same upstream space id on both sides: only the URL separates them."""
    settings.CHECKIN_API_URL = ""
    a = _space("iso-look-a", URL_A)
    b = _space("iso-look-b", URL_B)
    fake_dns(monkeypatch, {"roster-a.example.net": [PUBLIC_IP], "roster-b.example.net": [PUBLIC_IP]})
    fake_upstream(monkeypatch, {
        "roster-a.example.net": FakeResponse(body=roster_body(row(mid=7, name="Ada Example"))),
        "roster-b.example.net": FakeResponse(body=b"null"),
    })

    assert [m["mid"] for m in _lookup(a, "Ada Example").json()] == [7]
    assert _lookup(b, "Ada Example").json() == []
    # And in the other order, with A's roster now warm in the cache.
    assert _lookup(b, "Ada Example").json() == []


def test_deployment_roster_keeps_its_original_transport(monkeypatch, settings):
    """Production shape: no own URL, so `requests.get` on CHECKIN_API_URL as before."""
    settings.CHECKIN_API_URL = "https://checkin.example.org/active"
    space = _space("iso-env")
    seen = {}

    class Response:
        status_code = 200
        headers = {}

        def iter_content(self, chunk_size):
            yield roster_body(row())

    def get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(
        "apps.checkin.transport._PinnedHTTPSConnection",
        lambda *a: pytest.fail("the guarded transport is for makerspace URLs only"),
    )

    assert [e.mid for e in client.fetch_roster(space, cached=False)] == [443]
    assert seen["url"] == "https://checkin.example.org/active"
    assert seen["allow_redirects"] is False


def test_checked_in_without_any_roster_fails_closed_with_a_clear_503(settings):
    settings.CHECKIN_API_URL = ""
    space = _space("iso-unset")

    response = _lookup(space, "Ada Example")

    assert response.status_code == 503
    assert response.json()["code"] == "checkin_unavailable"
    assert "not set up" in response.json()["detail"]


# --- SSRF at fetch time ---------------------------------------------------------


@pytest.mark.parametrize(
    "url, dns",
    [
        ("https://127.0.0.1/active", {}),
        ("https://localhost/active", {"localhost": ["127.0.0.1"]}),
        ("https://169.254.169.254/latest/meta-data", {}),
        ("https://10.0.0.8/active", {}),
        ("https://100.64.1.1/active", {}),
        ("https://inside.example.net/active", {"inside.example.net": ["192.168.1.20"]}),
        ("https://mixed.example.net/active", {"mixed.example.net": [PUBLIC_IP, "10.0.0.8"]}),
        ("http://roster.example.net/active", {"roster.example.net": [PUBLIC_IP]}),
    ],
)
def test_saved_url_reaching_a_private_address_is_refused_before_connecting(
    monkeypatch, settings, url, dns
):
    """A row written behind the console's validation (raw SQL, an old restore, DNS
    that changed since save) is still refused at the moment of the fetch."""
    settings.CHECKIN_API_URL = ""
    space = _space(f"ssrf-{hashlib.sha256(url.encode()).hexdigest()[:10]}")
    Makerspace.objects.filter(pk=space.pk).update(checkin_api_url=url)
    space.refresh_from_db()
    if dns:
        fake_dns(monkeypatch, dns)
    calls = fake_upstream(monkeypatch, {})

    with pytest.raises(CheckinUnavailable) as caught:
        client.fetch_roster(space, cached=False)

    assert caught.value.reason == transport.REASON_REFUSED
    assert calls == []


def test_redirect_is_never_followed_even_towards_a_private_host(monkeypatch, settings):
    settings.CHECKIN_API_URL = ""
    space = _space("ssrf-redirect", URL_A)
    fake_dns(monkeypatch, {"roster-a.example.net": [PUBLIC_IP]})
    calls = fake_upstream(monkeypatch, {
        "roster-a.example.net": FakeResponse(
            status=302, body=b"", headers={"Location": "https://169.254.169.254/latest"}
        ),
    })

    with pytest.raises(CheckinUnavailable) as caught:
        client.fetch_roster(space, cached=False)

    assert caught.value.reason == transport.REASON_REDIRECT
    assert len(calls) == 1


def test_guarded_fetch_pins_the_vetted_address_and_caps_the_body(monkeypatch, settings):
    settings.CHECKIN_API_URL = ""
    settings.CHECKIN_MAX_RESPONSE_BYTES = 64
    space = _space("ssrf-cap", URL_A)
    fake_dns(monkeypatch, {"roster-a.example.net": [PUBLIC_IP]})
    calls = fake_upstream(monkeypatch, {
        "roster-a.example.net": FakeResponse(body=roster_body(row(), row(mid=2))),
    })

    with pytest.raises(CheckinUnavailable) as caught:
        client.fetch_roster(space, cached=False)

    assert caught.value.reason == transport.REASON_TOO_LARGE
    assert calls == [("roster-a.example.net", PUBLIC_IP, "/active")]


def test_lookup_applies_the_makerspaces_own_purpose(monkeypatch, settings):
    settings.CHECKIN_API_URL = ""
    space = _space("own-purpose", URL_A)
    space.checkin_required_purpose = "Tinkering"
    space.save(update_fields=["checkin_required_purpose"])
    fake_dns(monkeypatch, {"roster-a.example.net": [PUBLIC_IP]})
    fake_upstream(monkeypatch, {
        "roster-a.example.net": FakeResponse(body=roster_body(
            row(mid=1, name="Ada Example", purpose="Tinkering"),
            row(mid=2, name="Ada Example", purpose="Working on a project"),
        )),
    })

    rows = {m["mid"]: m for m in _lookup(space, "Ada Example").json()}

    assert rows[1]["eligible"] is True
    assert rows[2]["eligible"] is False and rows[2]["reason"] == "purpose"
