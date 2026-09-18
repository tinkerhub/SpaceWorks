"""HOST-ONLY: these assertions read files outside the backend Docker build context.

The staff refresh cookie is the one piece of auth whose correct value depends on the
*transport* the operator chose, and it fails silently in both directions: a Secure cookie
on a plain-HTTP origin is dropped by the browser, while a non-Secure `SameSite=Lax`
cookie is not sent from a separate frontend origin. Login succeeds either way and hands
out a short-lived access token, so the symptom is "everyone gets signed out on reload",
with nothing in the logs.
"""

from pathlib import Path
import re

import yaml


# ./backend is mounted at /app in the dev container, so parents[2] there is the
# filesystem root rather than the repo. The dev compose file exposes the repository
# read-only at /workspace; host runs fall back to the test's own location. Same shape as
# tests/test_env_surface_drift.py.
MOUNTED_REPO_ROOT = Path("/workspace")
ROOT = (
    MOUNTED_REPO_ROOT
    if (MOUNTED_REPO_ROOT / "backend" / "config" / "settings.py").is_file()
    else Path(__file__).resolve().parents[2]
)

COOKIE_KEYS = ("AUTH_COOKIE_SAMESITE", "AUTH_COOKIE_SECURE")
# They share one YAML anchor, but assert per service: a variable added to `backend`
# alone would not reach the others.
BACKEND_SERVICES = ("backend", "migrate", "worker", "beat")


class _ComposeLoader(yaml.SafeLoader):
    """`ports: !reset []` is a Compose tag, not plain YAML, and the overlays use it."""


_ComposeLoader.add_constructor("!reset", lambda loader, node: None)


def test_production_compose_passes_the_cookie_posture_to_every_backend_service():
    document = yaml.load(  # noqa: S506 - SafeLoader plus the Compose !reset tag
        (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"),
        Loader=_ComposeLoader,
    )

    for service in BACKEND_SERVICES:
        environment = document["services"][service]["environment"]
        missing = sorted(key for key in COOKIE_KEYS if key not in environment)
        assert not missing, (
            f"docker-compose.prod.yml service {service!r} does not pass {missing}. "
            "settings.py reads them, but a variable Compose never forwards cannot be "
            "configured at all: an operator setting it in .env sees no effect, and a "
            "plain-HTTP deployment keeps dropping the refresh cookie."
        )


def test_the_tls_overlay_forces_secure_cookies_back_on():
    overlay = yaml.load(  # noqa: S506 - SafeLoader plus the Compose !reset tag
        (ROOT / "docker" / "compose.tls.yml").read_text(encoding="utf-8"),
        Loader=_ComposeLoader,
    )
    environment = overlay["services"]["backend"]["environment"]

    assert str(environment.get("AUTH_COOKIE_SECURE")).lower() == "true", (
        "The TLS overlay must force AUTH_COOKIE_SECURE=True rather than defaulting it. "
        "setup.sh writes False for the plain-HTTP origin it configures, and that value "
        "stays in .env when an operator later switches to this overlay -- leaving a "
        "long-lived refresh cookie with no Secure attribute on an HTTPS deployment, "
        "which an http:// auth path can transmit before the redirect."
    )
    assert "AUTH_COOKIE_SAMESITE" not in environment, (
        "SameSite must stay operator-controlled through .env: the bundled frontend is "
        "same-origin (Lax) but a frontend on a separate origin needs None. Pinning it "
        "here would silently break one of the two topologies."
    )


def test_guided_setup_writes_an_http_safe_cookie_posture():
    setup = (ROOT / "setup.sh").read_text(encoding="utf-8")

    # Guided setup writes exactly one origin, over http://, so the cookie has to match.
    assert re.search(r"^ENABLE_HTTPS=false$", setup, re.MULTILINE), (
        "setup.sh no longer writes a plain-HTTP deployment; the cookie posture below "
        "was chosen to match that and must be re-derived."
    )
    assert re.search(r"^AUTH_COOKIE_SAMESITE=Lax$", setup, re.MULTILINE), (
        "setup.sh must write AUTH_COOKIE_SAMESITE=Lax. The settings.py default is None, "
        "which requires Secure, which a browser refuses to store over http://."
    )
    assert re.search(r"^AUTH_COOKIE_SECURE=False$", setup, re.MULTILINE), (
        "setup.sh must write AUTH_COOKIE_SECURE=False for the plain-HTTP origin it "
        "configures, or staff can log in but are signed out again on the next reload."
    )


def test_example_env_defaults_to_an_http_safe_cookie_posture():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert re.search(r"^ENABLE_HTTPS=false$", example, re.MULTILINE)
    assert re.search(r"^CORS_ALLOWED_ORIGINS=http://", example, re.MULTILINE)
    assert re.search(r"^PUBLIC_APP_BASE_URL=http://", example, re.MULTILINE)
    assert re.search(r"^AUTH_COOKIE_SAMESITE=Lax$", example, re.MULTILINE), (
        ".env.example must make Lax the active default for its bundled same-origin "
        "plain-HTTP topology, not only mention it in the commented TLS example."
    )
    assert re.search(r"^AUTH_COOKIE_SECURE=False$", example, re.MULTILINE), (
        ".env.example must disable Secure for its active plain-HTTP origin or browsers "
        "silently discard the staff refresh cookie."
    )


def test_existing_env_cookie_backfill_is_guarded_by_the_recorded_topology():
    setup = (ROOT / "setup.sh").read_text(encoding="utf-8")

    guarded_backfill = re.search(
        r"if ! grep -q '\^AUTH_COOKIE_SAMESITE=' \.env.*?"
        r"if \{ ! grep -q '\^ENABLE_HTTPS=' \.env.*?"
        r"grep -Eq '\^CORS_ALLOWED_ORIGINS=http://.*?"
        r"grep -Eq '\^PUBLIC_APP_BASE_URL=http://.*?"
        r"if ! grep -q '\^AUTH_COOKIE_SAMESITE=' \.env; then\s+"
        r"printf '\\nAUTH_COOKIE_SAMESITE=Lax\\n' >> \.env.*?"
        r"if ! grep -q '\^AUTH_COOKIE_SECURE=' \.env; then\s+"
        r"printf '\\nAUTH_COOKIE_SECURE=False\\n' >> \.env",
        setup,
        re.DOTALL,
    )
    assert guarded_backfill, (
        "Existing .env files must receive cookie defaults only after setup.sh proves "
        "that ENABLE_HTTPS is absent/false and both recorded public origins use http://."
    )
    assert setup.count("printf '\\nAUTH_COOKIE_SAMESITE=Lax\\n' >> .env") == 1
    assert setup.count("printf '\\nAUTH_COOKIE_SECURE=False\\n' >> .env") == 1
    assert "docs/self-hosting.md" in setup[guarded_backfill.end() :], (
        "An ambiguous existing topology must warn operators where to configure both "
        "cookie variables instead of silently choosing values."
    )


def test_tls_overlay_pins_and_caps_caddy_and_unpublishes_minio():
    overlay_path = ROOT / "docker" / "compose.tls.yml"
    overlay_text = overlay_path.read_text(encoding="utf-8")
    overlay = yaml.load(  # noqa: S506 - SafeLoader plus the Compose !reset tag
        overlay_text,
        Loader=_ComposeLoader,
    )

    caddy = overlay["services"]["caddy"]
    assert re.fullmatch(r"caddy:2\.\d+\.\d+-alpine", caddy["image"]), (
        "The TLS terminator must use an explicit Caddy patch release, not the rolling "
        "caddy:2-alpine tag that scripts/update.sh does not pull."
    )
    assert caddy.get("logging") == {
        "driver": "json-file",
        "options": {"max-size": "10m", "max-file": "5"},
    }

    minio = overlay["services"]["minio"]
    assert minio.get("ports") is None, (
        "The TLS overlay must reset inherited MinIO host ports so plaintext port 9000 "
        "is not reachable outside the Compose network."
    )
    assert minio.get("expose") == ["9000"]
