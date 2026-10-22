"""HOST-ONLY: every public proxy config must deny /api/v1/internal/*.

Those routes (api/v1/internal/tls-check) are infra-only. deploy/Caddyfile once
proxied all /api/* to the backend without the deny, exposing them on TLS-mode
self-hosts while Caddyfile.saas and frontend/nginx.conf denied them.
"""

import re
from pathlib import Path

import pytest


# Repository root resolution follows tests/test_platform_update_scripts.py.
MOUNTED_REPO_ROOT = Path("/workspace")
ROOT = (
    MOUNTED_REPO_ROOT
    if (MOUNTED_REPO_ROOT / "backend" / "config" / "settings.py").is_file()
    else Path(__file__).resolve().parents[2]
)
pytestmark = pytest.mark.skipif(
    not (ROOT / "install.sh").exists(),
    reason="host-only: the repository root is not in the backend image",
)

CADDY_DENY = re.compile(r"handle\s+/api/v1/internal/\*\s*\{\s*respond\s+403\s*\}")
NGINX_DENY = re.compile(r"location\s+(\^~\s+)?/api/v1/internal/\s*\{\s*return\s+403;\s*\}")


def _strip_comments(text):
    return re.sub(r"#[^\n]*", "", text)


def _caddyfiles():
    return sorted(ROOT.glob("deploy/Caddyfile*"))


def test_every_known_caddyfile_is_discovered():
    assert {p.name for p in _caddyfiles()} >= {"Caddyfile", "Caddyfile.saas"}, (
        "The glob must find both so the deny check below cannot pass vacuously."
    )


def test_every_caddyfile_denies_internal_routes():
    missing = [
        p.name for p in _caddyfiles()
        if not CADDY_DENY.search(_strip_comments(p.read_text(encoding="utf-8")))
    ]
    assert not missing, (
        f"Missing /api/v1/internal/* deny in: {', '.join(missing)}. These routes are "
        "infra-only (Caddy's on_demand_tls ask reaches backend:8000 directly); "
        "without the deny they are publicly reachable."
    )


def test_nginx_denies_internal_routes():
    path = ROOT / "frontend" / "nginx.conf"
    assert NGINX_DENY.search(_strip_comments(path.read_text(encoding="utf-8"))), (
        "Missing /api/v1/internal/* deny in frontend/nginx.conf. These routes are "
        "infra-only (Caddy's on_demand_tls ask reaches backend:8000 directly); "
        "without the deny they are publicly reachable."
    )


CADDY_READINESS_DENY = re.compile(r"handle\s+/api/v1/health/readiness\*\s*\{\s*respond\s+403\s*\}")
NGINX_READINESS_DENY = re.compile(r"location\s+/api/v1/health/readiness\s*\{\s*return\s+403;\s*\}")


def test_every_public_proxy_denies_readiness():
    """Readiness is a deployment probe: Compose healthchecks and update.sh call it on
    localhost:8000 inside the backend container, never through a public proxy."""
    missing = [
        p.name for p in _caddyfiles()
        if not CADDY_READINESS_DENY.search(_strip_comments(p.read_text(encoding="utf-8")))
    ]
    nginx = _strip_comments((ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8"))
    if not NGINX_READINESS_DENY.search(nginx):
        missing.append("frontend/nginx.conf")
    assert not missing, f"Missing /api/v1/health/readiness deny in: {', '.join(missing)}."
