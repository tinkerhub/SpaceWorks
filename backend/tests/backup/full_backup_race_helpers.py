"""Query-observed PostgreSQL barriers, never a sleep-based race assertion."""

from queue import Queue
from threading import Event
from time import monotonic

from django.db import close_old_connections, connection, connections


def independent_job(action, pids=None):
    close_old_connections()
    try:
        if pids is not None:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids.put(cursor.fetchone()[0])
        return action()
    finally:
        connections.close_all()


def wait_until_blocked(blocked_pid, blocker_pid):
    deadline = monotonic() + 10
    tick = Event()
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_blocking_pids(%s)", [blocked_pid])
            if blocker_pid in cursor.fetchone()[0]:
                return
        tick.wait(0.01)
    raise AssertionError("PostgreSQL never reported the expected blocking connection")


def hold_publication(monkeypatch):
    """Pause only after real SHARE/run locks, before ordinary row locks."""
    from apps.backup import promotion

    arrived, release, pids = Event(), Event(), Queue()
    original = promotion._lock_makerspaces

    def held(ids):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            pids.put(cursor.fetchone()[0])
        arrived.set()
        assert release.wait(10), "test did not release publication"
        return original(ids)

    monkeypatch.setattr(promotion, "_lock_makerspaces", held)
    return arrived, release, pids
