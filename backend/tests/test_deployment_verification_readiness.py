"""Run the actual inline readiness Python with a controlled urllib transport."""

import urllib.request

import pytest

from tests.deployment_verification_fakes import ROOT, SENTINEL, shell_step


pytestmark = pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout")


@pytest.mark.parametrize(("status", "exception", "exit_code"), [
    (200, None, 0), (201, None, 1), (204, None, 1), (301, None, 1),
    (302, None, 1), (401, None, 1), (503, None, 1),
    (None, OSError(SENTINEL), 1), (None, TimeoutError(SENTINEL), 1),
    (None, ValueError(SENTINEL), 1),
])
def test_private_probe_accepts_only_200_without_proxies_redirects_or_body_reads(
    monkeypatch, capsys, status, exception, exit_code,
):
    script = shell_step("deploy", 1)
    code = script.split("python -c '", 1)[1].split("\n' >/dev/null", 1)[0]
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self, *_args):
            pytest.fail("The private readiness payload must never be read")

    Response.status = status

    class Opener:
        def open(self, url, timeout):
            calls.append((url, timeout))
            if exception:
                raise exception
            return Response()

    def build(*handlers):
        assert len(handlers) == 2
        proxy, redirect = handlers
        assert isinstance(proxy, urllib.request.ProxyHandler) and proxy.proxies == {}
        assert isinstance(redirect, urllib.request.HTTPRedirectHandler)
        assert redirect.redirect_request(None, None, 302, SENTINEL, {},
                                         "https://private.invalid/secret") is None
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build)
    with pytest.raises(SystemExit) as exited:
        exec(compile(code, "<actual workflow readiness probe>", "exec"), {})
    assert exited.value.code == exit_code
    assert calls == [("http://localhost:8000/api/v1/health/readiness/", 3)]
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
