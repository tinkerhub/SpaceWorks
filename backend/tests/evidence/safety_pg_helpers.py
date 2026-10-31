"""Owned PG sessions, complete SQL capture, observed waits and finite cleanup."""
import queue
import threading
import time
from uuid import uuid4

from django.db import close_old_connections, connection, connections


def observe_wait(waiter, blocker, executing, *, table, clause):
    deadline = time.monotonic() + 5
    last = None
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type, %s = ANY(pg_blocking_pids(pid)), query "
                "FROM pg_stat_activity WHERE pid = %s", [blocker, waiter],
            )
            last = cursor.fetchone()
        if last and last[0] == "Lock" and last[1]:
            sql = " ".join(executing["second"].split())
            reported = " ".join(last[2].split())
            prefix = sql.split("%s", 1)[0]
            length = min(len(prefix), len(reported))
            assert length >= 64 and reported[:length] == prefix[:length], (reported, sql)
            assert f'FROM "{table}"' in sql and clause in sql, sql
            return sql
        threading.Event().wait(0.01)
    raise AssertionError(f"Expected PG blocking edge was not observed: {last!r}")


def policy_claim_race(first, second, *, pause_after, waiter_clause):
    """Pause after a real SQL statement, retaining its actual transaction locks."""
    assert connection.vendor == "postgresql", "Real PostgreSQL is required; no environment skip"
    assert connection.get_autocommit() and not connection.in_atomic_block
    ready, release = threading.Event(), threading.Event()
    connected = queue.Queue()
    pids, tags, outcomes, executing, captured = {}, {}, {}, {}, {}
    workers = []
    token = uuid4().hex

    def run(name, operation):
        announced = False
        try:
            close_old_connections()
            tags[name] = f"evidence-safety-{token}-{name}"
            captured[name] = []
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
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
                    assert release.wait(12), "Real SQL checkpoint was not released"
                return result

            with connection.execute_wrapper(capture):
                outcomes[name] = operation(), None
        except Exception as exc:
            outcomes[name] = None, exc
            if not announced:
                connected.put((name, exc))
        finally:
            connections.close_all()

    def start(name, operation):
        worker = threading.Thread(target=run, args=(name, operation), daemon=True)
        workers.append((name, worker))
        worker.start()
        announced, error = connected.get(timeout=5)
        assert announced == name
        if error is not None:
            raise error

    try:
        start("first", first)
        assert ready.wait(5), "First operation never reached its real SQL checkpoint"
        start("second", second)
        assert pids["first"] != pids["second"]
        waited_sql = observe_wait(
            pids["second"], pids["first"], executing,
            table="makerspaces_makerspace", clause=waiter_clause,
        )
    finally:
        release.set()
        deadline = time.monotonic() + 20
        for _, worker in workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        cleanup_errors = []
        for name, worker in workers:
            if worker.is_alive() and name in pids:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE pid = %s AND application_name = %s", [pids[name], tags[name]],
                        )
                except Exception as exc:
                    cleanup_errors.append(exc)
                finally:
                    worker.join(timeout=5)
        assert all(not worker.is_alive() for _, worker in workers), "Owned PG worker leaked"
        if cleanup_errors:
            raise cleanup_errors[0]
    assert set(outcomes) == {"first", "second"}
    for _, error in outcomes.values():
        if error is not None:
            raise error  # Deadlocks/timeouts are failures; never retry or accept.
    return outcomes["first"][0], outcomes["second"][0], pids, captured, waited_sql
