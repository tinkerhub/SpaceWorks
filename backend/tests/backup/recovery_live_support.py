"""Child process and dedicated Redis isolation for the slow live-generation proof."""

import json
import os
import signal
import subprocess
import sys
import time
from urllib.parse import quote, urlsplit

from django.conf import settings
from django.db import connection

from tests.backup.recovery_test_support import repo_root


def dedicated_url():
    url = os.environ.get("SPACEWORKS_TEST_REDIS_URL")
    assert url, (
        "Required: SPACEWORKS_TEST_REDIS_URL=redis://DEDICATED-TEST-REDIS:6379/DB. "
        "Provision a disposable broker/database used only for this proof; no production/shared broker fallback or purge is allowed."
    )
    parsed = urlsplit(url)
    assert parsed.scheme in {"redis", "rediss"} and parsed.hostname
    assert parsed.path == "/13", "This proof requires dedicated Redis database 13."
    assert os.environ.get("SPACEWORKS_TEST_REDIS_DEDICATED") == "1", "Confirm dedicated broker ownership with SPACEWORKS_TEST_REDIS_DEDICATED=1."
    return url


def database_url():
    assert not connection.in_atomic_block, "Live worker needs committed rows: use django_db(transaction=True)."
    cfg = connection.settings_dict
    assert cfg["ENGINE"].endswith("postgresql"), "Live proof requires real PostgreSQL commit visibility."
    assert os.environ.get("SPACEWORKS_TEST_LIVE_DB_NAME") == cfg["NAME"], (
        "Set SPACEWORKS_TEST_LIVE_DB_NAME to the exact parent pytest dedicated test DB name; never run this against the deployment DB."
    )
    assert cfg.get("HOST") and not cfg["HOST"].startswith("/"), "Child worker requires the parent's explicit TCP PG endpoint."
    return "postgres://" + quote(cfg["USER"], safe="") + ":" + quote(cfg.get("PASSWORD") or "", safe="") + "@" + cfg["HOST"] + ":" + str(cfg.get("PORT") or 5432) + "/" + quote(cfg["NAME"], safe="")


def wait_until(predicate, *, reason, process=None, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        assert process is None or process.poll() is None, "Private worker exited before " + reason
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for " + reason + "; inspect this proof's private worker logs.")


def worker(tmp_path, generation, prefix, url):
    env = dict(os.environ, DATABASE_URL=database_url(), DJANGO_SETTINGS_MODULE="config.settings",
        SPACEWORKS_TASK_GENERATION=generation, SPACEWORKS_TEST_REDIS_PREFIX=prefix,
        SPACEWORKS_TEST_REDIS_URL=url, AUDIT_MAC_MASTER_KEY=settings.AUDIT_MAC_MASTER_KEY,
        CELERY_BROKER_URL=url, CELERY_BROKER_READ_URL=url,
        CELERY_BROKER_WRITE_URL=url, CELERY_RESULT_BACKEND=url)
    # Pass the exact parent's encrypted-field continuity into the child. Values
    # stay in its environment and are never placed in argv or printed evidence.
    for name in ("API_CLIENT_ENC_KEY", "PII_MASTER_KEY", "PII_MASTER_KEY_PREVIOUS", "PII_SEARCH_HASH_KEY"):
        value = getattr(settings, name, None)
        if value is not None:
            env[name] = str(value)
    log = (tmp_path / ("worker-" + generation + ".log")).open("wb")
    try:
        process = subprocess.Popen([sys.executable, "-B", "-m", "tests.backup.recovery_live_tasks", "worker"],
            cwd=repo_root() / "backend", env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
    finally:
        log.close()
    return process


def stop_worker(process, *, kill=False):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL if kill else signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def retained_message_ids(redis, prefix):
    """Read only our prefix; messages can move from unacked back to old queue."""
    found = set()
    for key in redis.scan_iter(match=prefix + "*"):
        kind = redis.type(key)
        values = redis.lrange(key, 0, -1) if kind == b"list" else redis.hvals(key) if kind == b"hash" and key.endswith(b"unacked") else []
        for raw in values:
            try:
                value = json.loads(raw)
                message = value[0] if isinstance(value, list) else value
                found.add(message["headers"]["id"])
            except (ValueError, TypeError, KeyError):
                pass
    return found
