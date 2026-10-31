"""Real urllib behavior using loopback only; never contact a deployment endpoint."""

import signal
import time

import pytest

from tests.deployment_verification_fakes import ROOT, SHA
from tests.deployment_verification_fakes_http import alarm_handler, load_checker, loopback_server


pytestmark = [
    pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout"),
    pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="requires POSIX interval timers"),
]


def test_urllib_refuses_redirect_without_fetching_the_target(capsys):
    checker = load_checker()
    opener = checker.build_opener(checker.ProxyHandler({}), checker.RefuseRedirects())
    with loopback_server() as (origin, requests), alarm_handler(checker):
        # Only the internal transport helper gets HTTP loopback. Public config stays HTTPS-only.
        assert checker.check_once(opener, origin + "/redirect", SHA)
        assert len(requests) == 1
        assert requests[0].startswith("/redirect?")
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_explicit_empty_proxy_handler_ignores_environment_proxies(monkeypatch):
    checker = load_checker()
    with loopback_server() as (origin, requests), loopback_server() as (proxy, proxy_requests):
        for key in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
            monkeypatch.setenv(key, proxy)
        for key in ("no_proxy", "NO_PROXY"):
            monkeypatch.setenv(key, "")
        opener = checker.build_opener(checker.ProxyHandler({}), checker.RefuseRedirects())
        with alarm_handler(checker):
            assert checker.check_once(opener, origin + "/metadata", SHA) is None
        assert len(requests) == 1
        assert proxy_requests == []


def test_slow_drip_has_a_total_deadline_even_when_every_socket_read_is_timely(monkeypatch, capsys):
    checker = load_checker()
    monkeypatch.setattr(checker, "REQUEST_TIMEOUT", 0.15)
    opener = checker.build_opener(checker.ProxyHandler({}), checker.RefuseRedirects())
    with loopback_server() as (origin, requests), alarm_handler(checker):
        started = time.monotonic()
        problem = checker.check_once(opener, origin + "/drip", SHA)
        elapsed = time.monotonic() - started
        assert problem == "request failed or metadata was invalid"
        # The complete body drips for >1.5s, but each byte arrives within the socket timeout.
        assert elapsed < 1.2
        assert len(requests) == 1
        assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    output = capsys.readouterr()
    assert output.out == output.err == ""
