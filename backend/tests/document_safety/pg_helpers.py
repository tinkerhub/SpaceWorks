"""Owned PostgreSQL workers, actual SQL/PIDs/blocking edges, bounded cleanup."""
import queue
import threading
import time
from uuid import uuid4

from django.db import close_old_connections, connection, connections


def statement(table, clause):
    return lambda sql: f'FROM "{table}"' in sql and clause in sql


def blocking_edge(waiter, blocker, executing, table, clause):
    deadline = time.monotonic() + 5
    last = None
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type, %s = ANY(pg_blocking_pids(pid)), query "
                "FROM pg_stat_activity WHERE pid=%s", [blocker, waiter],
            )
            last = cursor.fetchone()
        if last and last[0] == "Lock" and last[1]:
            sql = " ".join(executing["second"].split())
            reported = " ".join(last[2].split())
            prefix = sql.split("%s", 1)[0]
            length = min(len(prefix), len(reported))
            assert length >= 40 and prefix[:length] == reported[:length], (sql, last)
            assert table in sql and clause in sql, (sql, last)
            return sql
        # Poll a measured server condition; no sleep-based winner assumptions.
        threading.Event().wait(0.01)
    raise AssertionError(f"Missing actual PG blocking edge: {last!r}")


def race(first, second, *, pause_after, table, clause, before_release=None):
    assert connection.vendor == "postgresql", "Real PG required; no SQLite skip"
    assert connection.get_autocommit() and not connection.in_atomic_block
    ready, release = threading.Event(), threading.Event()
    connected = queue.Queue()
    pids, tags, captured, executing, outcomes = {}, {}, {}, {}, {}
    workers = []
    token = uuid4().hex

    def run(name, operation):
        announced = False
        try:
            close_old_connections()
            tags[name] = f"documents-{token}-{name}"
            captured[name] = []
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout='8s'")
                cursor.execute("SET statement_timeout='12s'")
                cursor.execute("SELECT set_config('application_name', %s, false)", [tags[name]])
                cursor.execute("SELECT pg_backend_pid()")
                pids[name] = cursor.fetchone()[0]
            connected.put((name, None))
            announced = True

            def capture(execute, sql, params, many, context):
                captured[name].append((sql, params))
                executing[name] = sql
                result = execute(sql, params, many, context)
                if name == "first" and pause_after(sql) and not ready.is_set():
                    assert connection.in_atomic_block
                    ready.set()
                    assert release.wait(12), "SQL checkpoint was never released"
                return result

            with connection.execute_wrapper(capture):
                outcomes[name] = (operation(), None)
        except BaseException as exc:
            outcomes[name] = (None, exc)
            if not announced:
                connected.put((name, exc))
        finally:
            connections.close_all()

    def start(name, operation):
        thread = threading.Thread(target=run, args=(name, operation), daemon=True)
        workers.append((name, thread))
        thread.start()
        announced, error = connected.get(timeout=5)
        assert announced == name
        if error:
            raise error

    try:
        start("first", first)
        assert ready.wait(5), "First operation missed its actual SQL checkpoint"
        start("second", second)
        assert pids["first"] != pids["second"]
        waited = blocking_edge(pids["second"], pids["first"], executing, table, clause)
        if before_release:
            before_release(pids, captured)
    finally:
        release.set()
        deadline = time.monotonic() + 20
        for _, thread in workers:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        for name, thread in workers:
            if thread.is_alive() and name in pids:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE pid=%s AND application_name=%s", [pids[name], tags[name]],
                    )
                thread.join(timeout=5)
        assert all(not thread.is_alive() for _, thread in workers), "Owned worker leaked"
    assert set(outcomes) == {"first", "second"}
    for _, error in outcomes.values():
        if error:
            raise error  # No deadlock/timeout acceptance, retries or fake guards.
    return outcomes["first"][0], outcomes["second"][0], captured, pids, waited


def assert_no_maker_upgrade(captured, worker):
    locks = [sql for sql, _ in captured[worker]
             if 'FROM "makerspaces_makerspace"' in sql and " FOR " in sql]
    assert locks, captured[worker]
    assert all("FOR NO KEY UPDATE" in sql for sql in locks), locks


def assert_maker_key_share_compatible(pids, captured):
    """Prove the waiter passed its Maker lock while canonical transfer owns FKs."""
    assert_no_maker_upgrade(captured, "second")
    assert any(sql == "SET CONSTRAINTS ALL IMMEDIATE" for sql, _ in captured["first"])
    assert any(sql.startswith('INSERT INTO "operations_inventoryadjustment"')
               for sql, _ in captured["first"])
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT locktype, mode, granted FROM pg_locks "
            "WHERE pid=%s AND relation='makerspaces_makerspace'::regclass",
            [pids["first"]],
        )
        # Canonical transfer's real immediate FK checks took relation ROW SHARE.
        assert ("relation", "RowShareLock", True) in cursor.fetchall()
