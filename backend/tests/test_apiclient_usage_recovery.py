"""Deterministic crash/race coverage; Redis is entirely in memory."""

import re
from datetime import timedelta
from threading import Barrier, Event, current_thread
from uuid import UUID

import pytest
from django.db import DatabaseError
from django.db.models.query import QuerySet
from django.test import RequestFactory
from redis.exceptions import ResponseError

from apps.apiclients import telemetry
from apps.apiclients.models import ApiClient
from tests.apiclient_usage_helpers import (
    IP, KEY, NOW, OBSERVED, FlushWorker, ThreadSafeRedis,
    assert_seen, flush, make_client, seed,
)
from tests.test_apiclient_usage_telemetry import FakeRedis

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("redis_class", [FakeRedis, ThreadSafeRedis])
def test_redis_fakes_refuse_collision_and_transfer_expiry(redis_class):
    fake = redis_class()
    fake.hset("source", "client", "source-payload")
    fake.expire("source", 123)
    fake.hset("destination", "client", "destination-payload")
    fake.expire("destination", 456)
    assert not fake.renamenx("source", "destination")
    assert fake.hashes == {
        "source": {"client": "source-payload"},
        "destination": {"client": "destination-payload"},
    }
    assert fake.expiries == {"source": 123, "destination": 456}
    fake.delete("destination")
    assert fake.expiries == {"source": 123}
    assert fake.renamenx("source", "destination")
    assert fake.hashes == {"destination": {"client": "source-payload"}}
    assert fake.expiries == {"destination": 123}
    with pytest.raises(ResponseError, match="no such key"):
        fake.renamenx("missing", "destination")
    assert fake.expiries == {"destination": 123}
    fake.delete("destination")
    assert fake.hashes == fake.expiries == {}


@pytest.mark.parametrize("failure", ["db-write", "read"])
def test_detached_bucket_survives_failed_flush(monkeypatch, failure):
    fake, client = ThreadSafeRedis(), make_client()
    seed(fake, KEY, client)
    unknown = f"{KEY}:unknown"
    seed(fake, unknown, client, ttl=17)
    calls, failures = [], [failure]
    real_update = QuerySet.bulk_update

    def update(queryset, objects, fields, **kwargs):
        calls.append([obj.pk for obj in objects])
        result = real_update(queryset, objects, fields, **kwargs)
        if failures == ["db-write"]:
            failures.clear()
            raise DatabaseError("injected after SQL; transaction must roll back")
        return result

    def read(_key, _payload):
        if failures == ["read"]:
            failures.clear()
            raise RuntimeError("crash after detach")

    monkeypatch.setattr(QuerySet, "bulk_update", update)
    fake.after_read = read
    with pytest.raises(DatabaseError if failure == "db-write" else RuntimeError):
        flush(fake)
    drain = fake.renames[0][1]
    assert re.fullmatch(re.escape(KEY) + r":draining:[0-9a-f]{32}", drain)
    assert fake.expiries == {drain: 321, unknown: 17}
    assert KEY not in fake.hashes and fake.hashes[drain] == fake.hashes[unknown]
    assert fake.deleted == []
    assert_seen(client, None, None)
    assert flush(fake) == 1
    assert_seen(client)
    assert flush(fake) == 0
    assert len(calls) == (2 if failure == "db-write" else 1)
    assert len(fake.renames) == 1 and fake.reads == [drain, drain]
    assert fake.deleted == [drain]
    assert fake.expiries == {unknown: 17} and set(fake.hashes) == {unknown}


@pytest.mark.parametrize("kind", ["signed", "browser"])
@pytest.mark.parametrize("suffix", [":draining", ":draining:" + "a" * 32], ids=["legacy", "uuid"])
def test_legacy_and_unique_drains_are_retried_in_place(kind, suffix):
    fake = ThreadSafeRedis()
    client = make_client(client_type="browser" if kind == "browser" else "server")
    key = telemetry.bucket_key(kind, OBSERVED) + suffix
    seed(fake, key, client)
    assert flush(fake) == 1
    assert_seen(client)
    assert fake.renames == [] and fake.reads == [key] and fake.deleted == [key]
    assert fake.hashes == fake.expiries == {}


def test_malformed_names_and_current_or_future_buckets_are_untouched():
    fake, client = ThreadSafeRedis(), make_client()
    keys = [
        "other:usage:signed:202608191004", "apiclients:usage:admin:202608191004",
        "apiclients:usage:Signed:202608191004", KEY + "0", KEY[:-1],
        "apiclients:usage:signed:202602301004", "apiclients:usage:signed:202608192504",
        KEY + ":draining:", KEY + ":draining:" + "a" * 31,
        KEY + ":draining:" + "a" * 33, KEY + ":draining:" + "A" * 32,
        KEY + ":draining:" + "g" * 32, KEY + ":draining:legacy",
        KEY + ":draining:draining", KEY + ":extra", KEY + "\n",
    ] + [
        telemetry.bucket_key(kind, at) + suffix
        for kind in ("signed", "browser") for at in (NOW, NOW + timedelta(minutes=1))
        for suffix in ("", ":draining", ":draining:" + "b" * 32)
    ]
    for key in keys:
        seed(fake, key, client)
    original = {key: dict(value) for key, value in fake.hashes.items()}
    seed(fake, KEY, client)
    assert flush(fake) == 1
    assert_seen(client)
    assert fake.hashes == original and fake.expiries == dict.fromkeys(keys, 321)
    assert [source for source, _destination in fake.renames] == [KEY]


def test_uuid_collision_preserves_both_payloads_and_expiries(monkeypatch):
    fake, first, second = ThreadSafeRedis(), make_client(), make_client()
    collision = KEY + ":draining:" + "a" * 32
    seed(fake, KEY, first, ttl=123)
    seed(fake, collision, second, ttl=456)
    original = {key: dict(value) for key, value in fake.hashes.items()}
    monkeypatch.setattr(telemetry, "uuid4", lambda: UUID(hex="a" * 32))

    def abort_after_collision(_key, _payload):
        assert fake.hashes == original and fake.expiries == {KEY: 123, collision: 456}
        raise RuntimeError("stop before consuming the pre-existing drain")

    fake.after_read = abort_after_collision
    with pytest.raises(RuntimeError):
        flush(fake)
    assert fake.renames == [(KEY, collision)] and fake.deleted == []
    fake.after_read = lambda *_args: None
    monkeypatch.setattr(telemetry, "uuid4", lambda: UUID(hex="b" * 32))
    assert flush(fake) == 2
    assert_seen(first)
    assert_seen(second)
    assert fake.renames == [(KEY, collision), (KEY, KEY + ":draining:" + "b" * 32)]
    assert fake.hashes == fake.expiries == {}


@pytest.mark.parametrize(
    "error", [ResponseError("no such key"), ResponseError("NOPERM rename"), ConnectionError("offline")],
    ids=["missing-source", "redis-response", "connection"],
)
def test_detach_races_are_skipped_but_real_errors_are_logged(monkeypatch, caplog, error):
    fake, client = ThreadSafeRedis(), make_client()
    seed(fake, KEY, client)
    real_rename = fake.renamenx
    competing_drain = KEY + ":draining:" + "c" * 32

    def fail(source, _destination):
        if str(error) == "no such key":
            real_rename(source, competing_drain)  # Another flusher won the source.
        raise error

    monkeypatch.setattr(fake, "renamenx", fail)
    assert flush(fake) == 0
    retained = competing_drain if str(error) == "no such key" else KEY
    assert set(fake.hashes) == {retained} and fake.expiries == {retained: 321}
    assert fake.deleted == fake.reads == []
    assert ("api_client_usage_bucket_detach_failed" in caplog.text) == (retained == KEY)
    assert_seen(client, None, None)
    monkeypatch.setattr(fake, "renamenx", real_rename)
    assert flush(fake) == 1
    assert_seen(client)


def test_browser_namespace_and_timestamp_ip_pair_remain_monotonic():
    fake, server, browser = ThreadSafeRedis(), make_client(), make_client(client_type="browser")
    newer, other_ip = OBSERVED + timedelta(seconds=10), "2001:db8::1"
    browser_key = telemetry.bucket_key("browser", OBSERVED)
    seed(fake, KEY, server)
    seed(fake, browser_key, server, at=newer, ip=other_ip)
    seed(fake, browser_key, browser, at=newer, ip=other_ip)
    assert flush(fake) == 2
    assert_seen(server)
    assert_seen(browser, newer, other_ip)
    for at in (OBSERVED - timedelta(seconds=1), OBSERVED):
        seed(fake, KEY, server, at=at, ip="192.0.2.77")
        assert flush(fake) == 0
        assert_seen(server)
    seed(fake, KEY, server, at=newer, ip="not-an-ip")
    assert flush(fake) == 1
    assert_seen(server, newer, None)


@pytest.mark.parametrize("operation", ["get_redis_client", "pipeline", "hset", "expire", "execute"])
@pytest.mark.parametrize("kind", ["signed", "browser"])
def test_every_request_redis_failure_is_nonfatal(monkeypatch, caplog, operation, kind):
    fake, client = FakeRedis(), make_client()
    monkeypatch.setattr(telemetry, "get_redis_client", lambda: fake)

    def fail(*_args, **_kwargs):
        raise ConnectionError("injected Redis request failure")

    monkeypatch.setattr(telemetry if operation == "get_redis_client" else fake, operation, fail)
    recorder = getattr(telemetry, f"record_{kind}_client_observation")
    recorder(RequestFactory().get("/", REMOTE_ADDR=IP), client)
    assert "usage telemetry Redis write failed" in caplog.text
    assert_seen(client, None, None)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("latest_ip", [IP, "192.0.2.88"], ids=["same-ip", "changed-ip"])
def test_late_write_and_two_flushers_keep_distinct_generations(latest_ip):
    fake, client, old_only = ThreadSafeRedis(), make_client(), make_client()
    seed(fake, KEY, client)
    seed(fake, KEY, old_only)
    read, release = Event(), Event()
    worker = FlushWorker(fake)

    def pause(_key, _payload):
        if current_thread() is worker.thread:
            read.set()
            assert release.wait(5), "late-write flusher was not released"

    fake.after_read = pause
    worker.start()
    try:
        assert read.wait(5), "first flusher never detached/read the original"
        first_drain = fake.renames[0][1]
        assert KEY not in fake.hashes and fake.expiries[first_drain] == 321
        newer = OBSERVED + timedelta(seconds=10)
        seed(fake, KEY, client, at=newer, ip=latest_ip, ttl=222)
        assert set(fake.hashes[first_drain]) == {client.client_id, old_only.client_id}
        assert fake.expiries == {first_drain: 321, KEY: 222}
        assert flush(fake) == 2
    finally:
        release.set()
        result = worker.join()
    assert result == 0
    assert_seen(client, newer, latest_ip)
    assert_seen(old_only)
    destinations = [destination for source, destination in fake.renames if source == KEY]
    assert len(destinations) == len(set(destinations)) == 2
    assert all(re.fullmatch(re.escape(KEY) + r":draining:[0-9a-f]{32}", key) for key in destinations)
    assert fake.hashes == fake.expiries == {}


@pytest.mark.django_db(transaction=True)
def test_overlapping_retries_lock_rows_in_pk_order_and_are_idempotent(monkeypatch):
    fake, first, second = ThreadSafeRedis(), make_client(), make_client()
    drain = KEY + ":draining:" + "d" * 32
    seed(fake, drain, second)  # Deliberately reverse the insertion order.
    seed(fake, drain, first)
    gate, orders = Barrier(2), []
    real_fetch = QuerySet._fetch_all

    def fetch(queryset):
        if (
            queryset.model is ApiClient and queryset.query.select_for_update
            and queryset._result_cache is None
        ):
            orders.append(queryset.query.order_by)
            gate.wait(timeout=5)  # Before SQL runs, hence outside all DB row locks.
        return real_fetch(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", fetch)
    workers = [FlushWorker(fake), FlushWorker(fake)]
    for worker in workers:
        worker.start()
    try:
        results = [worker.join() for worker in workers]
    finally:
        gate.abort()
        for worker in workers:
            worker.thread.join(timeout=15)
        assert all(not worker.thread.is_alive() for worker in workers)
    assert sorted(results) == [0, 2]
    assert orders == [("pk",), ("pk",)]
    assert_seen(first)
    assert_seen(second)
    assert fake.renames == [] and fake.reads == [drain, drain]
    assert fake.deleted == [drain, drain] and fake.hashes == fake.expiries == {}
