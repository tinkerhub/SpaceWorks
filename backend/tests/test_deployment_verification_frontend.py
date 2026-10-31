"""Validate public configuration, bounded metadata parsing and rollout retries."""

from http.client import HTTPException
import json
import signal
import sys
from urllib.error import HTTPError, URLError

import pytest

from tests.deployment_verification_fakes import OTHER_SHA, ROOT, SENTINEL, SHA
from tests.deployment_verification_fakes_http import Opener, Response, alarm_handler, load_checker


pytestmark = [
    pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout"),
    pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="requires POSIX interval timers"),
]


@pytest.fixture
def checker():
    return load_checker()


@pytest.mark.parametrize(("url", "endpoint"), [
    ("https://frontend.example", "https://frontend.example/deployment.json"),
    ("https://frontend.example/app/", "https://frontend.example/app/deployment.json"),
    ("https://frontend.example:8443", "https://frontend.example:8443/deployment.json"),
])
def test_public_urls_become_https_metadata_endpoints(checker, url, endpoint):
    assert checker.validated_url(url) == endpoint


@pytest.mark.parametrize("url", [
    "", "http://example.test", "//example.test", "https:///path", "https://",
    "https://user@example.test", "https://user:secret@example.test", "https://@example.test",
    "https://example.test?", "https://example.test?token=secret", "https://example.test#",
    "https://example.test#secret", "https://example.test\\secret", "https://example.test:0",
    "https://example.test:65536", "https://example.test:bad", "https://example.test:-1",
    "https://[invalid", " https://example.test", "https://example.test/a b",
    *("https://example.test/" + char for char in ("\n", "\r", "\t", "\0", "\x1f", "\x7f")),
])
def test_unsafe_or_ambiguous_public_url_configuration_is_rejected(checker, url):
    with pytest.raises(ValueError):
        checker.validated_url(url)


def test_exact_small_json_is_accepted_and_request_bypasses_caches(checker):
    response = Response(content_type="application/json; charset=utf-8", length="56")
    opener = Opener(response)
    with alarm_handler(checker):
        assert checker.check_once(opener, "https://frontend.example/deployment.json", SHA) is None
    request, timeout = opener.calls[0]
    assert timeout == checker.REQUEST_TIMEOUT
    assert request.full_url.startswith("https://frontend.example/deployment.json?verification=")
    assert len(request.full_url.rsplit("=", 1)[1]) == 32
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Cache-control") == "no-cache, no-store"
    assert request.get_header("Pragma") == "no-cache"
    assert response.read_sizes == [1025] and response.closed


@pytest.mark.parametrize("body", [
    json.dumps({"revision": OTHER_SHA}).encode(), b'{"revision":null}',
    b"<html>SPA fallback</html>", b"\xff", b"{", b"[]", b"null", b'"revision"',
    b'{"revision":true}', b'{"revision":42}', b'{"revision":[]}', b'{"revision":{}}',
    json.dumps({"revision": SHA, "secret": SENTINEL}).encode(),
    ('{"revision":"' + SHA + '","revision":"' + SHA + '"}').encode(),
    ('{"revision":"' + SHA + '","revision":"' + OTHER_SHA + '"}').encode(),
    b" " * 1025,
])
def test_invalid_stale_duplicate_or_oversized_metadata_is_rejected(checker, body, capsys):
    with alarm_handler(checker):
        assert checker.check_once(Opener(Response(body=body)), "https://example.test/deployment.json", SHA)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_one_kib_boundary_is_inclusive_and_limits_actual_reads(checker):
    body = json.dumps({"revision": SHA}).encode()
    body += b" " * (1024 - len(body))
    with alarm_handler(checker):
        assert checker.check_once(Opener(Response(body=body, length="1024")), "https://example.test", SHA) is None
        assert checker.check_once(Opener(Response(body=body + b" ")), "https://example.test", SHA)


@pytest.mark.parametrize("response", [
    *(Response(status=code) for code in (201, 204, 301, 302, 307, 308, 401, 404, 500)),
    *(Response(content_type=kind) for kind in (None, "text/html", "text/plain", "application/problem+json")),
    *(Response(length=length) for length in ("1025", "-1", "invalid", "1.5")),
])
def test_status_mime_and_length_are_checked_before_reading_body(checker, response):
    with alarm_handler(checker):
        assert checker.check_once(Opener(response), "https://example.test", SHA)
    assert response.read_sizes == [] and response.closed


@pytest.mark.parametrize("error", [
    URLError(SENTINEL), HTTPError("https://secret.invalid/" + SENTINEL, 503, SENTINEL, {}, None),
    TimeoutError(SENTINEL), HTTPException(SENTINEL), OSError(SENTINEL),
])
def test_transport_and_body_errors_are_generic_and_cancel_deadline(checker, error, capsys):
    with alarm_handler(checker):
        for opener in (Opener(error), Opener(Response(error=error))):
            problem = checker.check_once(opener, "https://example.test", SHA)
            assert problem == "request failed or metadata was invalid"
            assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    assert SENTINEL not in str(capsys.readouterr())


@pytest.mark.parametrize(("responses", "code", "attempts"), [
    ([Response(body=b'{"revision":null}')], 1, 3),
    ([URLError(SENTINEL), Response(body=b'{"revision":null}'), Response()], 0, 3),
    ([Response()], 0, 1),
])
def test_cli_retries_are_finite_eventual_success_and_logs_redacted(
    checker, monkeypatch, capsys, responses, code, attempts,
):
    opener = Opener(*responses)
    pauses = []

    def build(*handlers):
        assert handlers[0].proxies == {}
        assert isinstance(handlers[1], checker.RefuseRedirects)
        return opener

    monkeypatch.setattr(checker, "build_opener", build)
    monkeypatch.setattr(checker, "MAX_ATTEMPTS", 3)
    monkeypatch.setattr(checker.time, "sleep", pauses.append)
    monkeypatch.setattr(sys, "argv", ["checker", "--expected-revision", SHA, "--url", "https://example.test"])
    monkeypatch.setenv("HTTPS_PROXY", "http://" + SENTINEL)
    with alarm_handler(checker):
        assert checker.main() == code
    assert len(opener.calls) == attempts
    assert pauses == [checker.RETRY_DELAY] * (attempts - 1)
    output = capsys.readouterr()
    assert SENTINEL not in output.out + output.err
    assert ("retry budget exhausted" in output.out) is (code == 1)
    assert ("deployment verified" in output.out) is (code == 0)


@pytest.mark.parametrize(("revision", "url"), [
    (SENTINEL, "https://example.test"), (SHA + "\n", "https://example.test"),
    (SHA, "https://user:" + SENTINEL + "@example.test?token=" + SENTINEL),
])
def test_invalid_cli_input_never_opens_transport_or_echoes_configuration(checker, monkeypatch, capsys, revision, url):
    monkeypatch.setattr(sys, "argv", ["checker", "--expected-revision", revision, "--url", url])
    monkeypatch.setattr(checker, "build_opener", lambda *_args: pytest.fail("invalid configuration opened transport"))
    assert checker.main() == 1
    output = capsys.readouterr()
    assert output.out == "Frontend verification failed: invalid revision or HTTPS URL configuration.\n"
    assert output.err == ""
