"""Every Django process a compose file starts must see the same `TOMBSTONED_APPS` (D3).

A tombstone is process-global: URL routing, admin registration and the schema depend on
it. When the variable lived only in `.env`, compose never passed it into any container,
so the setting was silently inert everywhere -- and a file passing it to `backend` alone
would run a worker or beat with a different app set.
"""

from pathlib import Path

import pytest
import yaml

MOUNTED_REPO_ROOT = Path("/workspace")
REPO_ROOT = (
    MOUNTED_REPO_ROOT
    if (MOUNTED_REPO_ROOT / "backend" / "config" / "settings.py").is_file()
    else Path(__file__).resolve().parent.parent.parent
)
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml", "docker-compose.cloud.yml")


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_every_django_service_receives_tombstoned_apps(name):
    services = yaml.safe_load((REPO_ROOT / name).read_text(encoding="utf-8"))["services"]
    # A service running Django settings is one that is handed SECRET_KEY.
    django_services = {
        service: config.get("environment") or {}
        for service, config in services.items()
        if "SECRET_KEY" in (config.get("environment") or {})
    }

    assert {"backend", "migrate"} <= set(django_services), name
    missing = sorted(svc for svc, env in django_services.items() if "TOMBSTONED_APPS" not in env)
    assert not missing, f"{name}: {missing} do not receive TOMBSTONED_APPS"
