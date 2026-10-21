"""Readiness keeps its strict status code for everyone, but only a direct in-deployment
caller (container healthcheck, update.sh) sees failure reasons and custody counts."""

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.backup.host_readiness import HostReadinessError
from apps.operations.views_health import ReadinessThrottle

pytestmark = pytest.mark.django_db

PROXIED = {"HTTP_X_FORWARDED_FOR": "203.0.113.7"}
COUNTS = {
    "below_floor_makerspaces": 3,
    "zero_recipient_makerspaces": 1,
    "undelivered_alarms": 2,
    "alarms_with_no_operator_address": 0,
}


@pytest.fixture(autouse=True)
def _ready(monkeypatch):
    cache.clear()
    monkeypatch.setattr("apps.encryption.readiness.assert_ready", lambda: None)
    monkeypatch.setattr("apps.backup.host_readiness.assert_host_ready", lambda _path: None)
    monkeypatch.setattr("apps.backup.readiness.archive_custody_readiness", lambda: COUNTS)
    yield
    cache.clear()


def _not_ready(monkeypatch):
    def refuse(_path):
        raise HostReadinessError("marker fence reservation mismatch for database oid 4242")

    monkeypatch.setattr("apps.backup.host_readiness.assert_host_ready", refuse)


def test_internal_caller_gets_custody_counts():
    response = APIClient().get(reverse("readiness"))

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "archive_custody": COUNTS}


@pytest.mark.parametrize(
    "extra",
    [PROXIED, {"REMOTE_ADDR": "8.8.8.8"}, {"HTTP_X_REAL_IP": "203.0.113.7"}],
    ids=["forwarded-for", "public-remote-addr", "real-ip"],
)
def test_proxied_or_public_caller_sees_only_status(extra):
    response = APIClient().get(reverse("readiness"), **extra)

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_failure_reason_is_internal_only(monkeypatch):
    _not_ready(monkeypatch)

    public = APIClient().get(reverse("readiness"), **PROXIED)
    internal = APIClient().get(reverse("readiness"))

    # The status code is the contract for every caller, including a provider probe.
    assert public.status_code == internal.status_code == 503
    assert public.json() == {"status": "unavailable"}
    assert "oid 4242" in internal.json()["detail"]


def test_proxied_callers_are_throttled_and_internal_probes_never_are(monkeypatch):
    monkeypatch.setattr(ReadinessThrottle, "THROTTLE_RATES", {"readiness": "2/min"})
    client = APIClient()

    codes = [client.get(reverse("readiness"), **PROXIED).status_code for _ in range(3)]
    internal = [client.get(reverse("readiness")).status_code for _ in range(5)]

    assert codes == [200, 200, 429]
    assert internal == [200] * 5


def test_liveness_stays_public_and_cheap():
    response = APIClient().get(reverse("health"), **PROXIED)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
