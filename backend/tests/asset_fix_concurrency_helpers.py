"""Bounded, independently connected PostgreSQL races; no workflow substitutes."""
from contextlib import contextmanager
import queue
import threading
import time
from uuid import uuid4

from django.db import close_old_connections, connection, connections
from django.db.models.signals import post_init

from apps.inventory.models import InventoryAsset


@contextmanager
def asset_reads(asset_id):
    """Observe actual ORM materialization without replacing reads or validators."""
    owner, statuses = threading.current_thread(), []

    def observed(sender, instance, **kwargs):
        if threading.current_thread() is owner and instance.pk == asset_id:
            statuses.append(instance.status)

    post_init.connect(observed, sender=InventoryAsset, weak=False)
    try:
        yield statuses
    finally:
        post_init.disconnect(observed, sender=InventoryAsset)


def _lock_edge(waiter, blocker, table, clause, executing):
    deadline = time.monotonic() + 5
    poll = threading.Event()
    last = None
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type, %s = ANY(pg_blocking_pids(pid)), query "
                "FROM pg_stat_activity WHERE pid = %s", [blocker, waiter],
            )
            last = cursor.fetchone()
        if last and last[0] == "Lock" and last[1]:
            # pg_stat_activity.query may stop at the server's 1024-byte limit,
            # before FROM on a wide model. The waiter captures its actual SQL
            # immediately before execute; the PID/blocker edge and matching
            # server-reported prefix bind that complete statement to this wait.
            query = " ".join(executing["second"].split())
            reported = " ".join(last[2].split())
            prefix = query.split("%s", 1)[0]
            assert len(prefix) >= 64 and len(reported) >= 64, (prefix, reported)
            common_length = min(len(prefix), len(reported))
            assert reported[:common_length] == prefix[:common_length], (reported, query)
            assert f'FROM "{table}"' in query, query
            assert clause in query, query
            return query
        poll.wait(0.01)
    raise AssertionError(f"No PostgreSQL blocker edge within 5s; last activity: {last!r}")


def race(first, second, reached, release, *, table, clause, before_second=None):
    """Observe the exact SQL wait, release, join, and close only owned sessions."""
    assert connection.vendor == "postgresql", "These regressions require real PostgreSQL"
    assert not connection.in_atomic_block and connection.get_autocommit()
    connected = queue.Queue()
    pids, outcomes, workers, tags, executing = {}, {}, [], {}, {}
    token = uuid4().hex

    def run(name, operation):
        announced = False
        try:
            close_old_connections()
            tags[name] = f"asset-fix-{token}-{name}"
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
                cursor.execute("SELECT set_config('application_name', %s, false)", [tags[name]])
                cursor.execute("SELECT pg_backend_pid()")
                pids[name] = cursor.fetchone()[0]
            connected.put((name, None))
            announced = True
            def capture_sql(execute, sql, params, many, context):
                executing[name] = sql
                return execute(sql, params, many, context)

            with connection.execute_wrapper(capture_sql):
                outcomes[name] = (operation(), None)
        except Exception as exc:
            outcomes[name] = (None, exc)
            if not announced:
                connected.put((name, exc))
        finally:
            connections.close_all()

    def start(name, operation):
        worker = threading.Thread(target=run, args=(name, operation), daemon=True)
        workers.append((name, worker))
        worker.start()
        announced_name, error = connected.get(timeout=5)
        assert announced_name == name
        if error is not None:
            raise error
        return pids[name]

    try:
        blocker = start("first", first)
        assert reached.wait(5), "First workflow did not reach its real audit/notification pause"
        if before_second:
            before_second()
        waiter = start("second", second)
        assert blocker != waiter, "The two contenders must own independent database sessions"
        query = _lock_edge(waiter, blocker, table, clause, executing)
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
                            "WHERE pid = %s AND application_name = %s",
                            [pids[name], tags[name]],
                        )
                except Exception as exc:
                    cleanup_errors.append(exc)
                finally:
                    worker.join(timeout=5)
        assert all(not worker.is_alive() for _, worker in workers), "Owned race worker did not exit"
        if cleanup_errors:
            raise cleanup_errors[0]

    assert set(outcomes) == {"first", "second"}
    for _, error in outcomes.values():
        if error is not None:
            # Deadlocks, lock timeouts and application errors are failures, never retries.
            raise error
    return outcomes["first"][0], outcomes["second"][0], pids, query
