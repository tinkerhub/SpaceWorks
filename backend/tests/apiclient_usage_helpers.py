"""In-memory Redis and bounded worker support for telemetry recovery tests."""

import fnmatch
import json
from datetime import UTC, datetime, timedelta
from threading import RLock, Thread

from django.db import close_old_connections, connection, connections
from redis.exceptions import ResponseError

from apps.apiclients import telemetry
from apps.apiclients.models import ApiClient

OBSERVED = datetime(2026, 8, 19, 10, 4, 20, tzinfo=UTC)
NOW = OBSERVED + timedelta(minutes=2)
IP = "198.51.100.24"
KEY = telemetry.bucket_key("signed", OBSERVED)


class ThreadSafeRedis:
    """Snapshots scans/reads; callbacks run outside the atomic Redis lock."""

    def __init__(self):
        self.lock = RLock()
        self.hashes = {}
        self.expiries = {}
        self.renames = []
        self.reads = []
        self.deleted = []
        self.after_read = lambda _key, _payload: None
        self.after_detach = lambda _source, _destination: None

    def hset(self, key, field, value):
        with self.lock:
            self.hashes.setdefault(key, {})[field] = value

    def expire(self, key, seconds):
        with self.lock:
            if key in self.hashes:
                self.expiries[key] = seconds

    def scan_iter(self, match):
        with self.lock:
            return iter([key for key in self.hashes if fnmatch.fnmatch(key, match)])

    def renamenx(self, source, destination):
        with self.lock:
            self.renames.append((source, destination))
            if source not in self.hashes:
                raise ResponseError("no such key")
            if destination in self.hashes:
                return False
            self.hashes[destination] = self.hashes.pop(source)
            self.expiries.pop(destination, None)
            if source in self.expiries:
                self.expiries[destination] = self.expiries.pop(source)
        self.after_detach(source, destination)
        return True

    def hgetall(self, key):
        with self.lock:
            self.reads.append(key)
            payload = dict(self.hashes.get(key, {}))
        self.after_read(key, payload)
        return payload

    def delete(self, *keys):
        with self.lock:
            self.deleted.extend(keys)
            for key in keys:
                self.hashes.pop(key, None)
                self.expiries.pop(key, None)


def make_client(*, client_type="server"):
    # No request authentication is exercised here; the rows/updates are real.
    return ApiClient.objects.create(
        label="Recovery client", client_type=client_type,
        secret_encrypted=b"unused", scopes=["public:read"],
    )


def seed(fake, key, client, *, at=OBSERVED, ip=IP, ttl=321):
    fake.hset(key, client.client_id, json.dumps({
        "timestamp": at.isoformat(), "resolved_ip": ip,
    }))
    fake.expire(key, ttl)


def flush(fake):
    return telemetry.flush_usage_observations(now=NOW, redis_client=fake)


def assert_seen(client, at=OBSERVED, ip=IP):
    client.refresh_from_db()
    assert (client.last_seen_at, client.last_seen_ip) == (at, ip)


class FlushWorker:
    def __init__(self, fake):
        self.fake = fake
        self.result = None
        self.error = None
        self.thread = Thread(target=self._run, daemon=True)

    def _run(self):
        close_old_connections()
        try:
            # Bound blocked DB statements too, so cleanup cannot strand a connection.
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '10s'")
            self.result = flush(self.fake)
        except BaseException as exc:
            self.error = exc
        finally:
            connections.close_all()
            close_old_connections()

    def start(self):
        self.thread.start()
        return self

    def join(self):
        self.thread.join(timeout=15)
        assert not self.thread.is_alive(), "telemetry worker did not terminate"
        if self.error is not None:
            raise self.error
        return self.result
