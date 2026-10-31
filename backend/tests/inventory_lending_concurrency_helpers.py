"""Bounded PostgreSQL lock observation for the inventory acceptance regression."""
import queue
import threading
import time

from django.db import close_old_connections, connection, connections


def _wait_for_lock_edge(waiter_pid, blocker_pid):
    deadline = time.monotonic() + 5
    poll = threading.Event()
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type, %s = ANY(pg_blocking_pids(pid)) "
                "FROM pg_stat_activity WHERE pid = %s",
                [blocker_pid, waiter_pid],
            )
            row = cursor.fetchone()
        if row is not None and row[0] == "Lock" and row[1]:
            return
        # Only the observed PostgreSQL wait edge establishes overlap.
        poll.wait(0.01)
    raise AssertionError("Second accept never waited on the first accept's PostgreSQL lock")


def race_accepts(first, second, reached, release):
    """Run real operations on independent connections and always release/close them."""
    if connection.in_atomic_block or not connection.get_autocommit():
        raise AssertionError("Race fixtures must be committed before worker connections start")
    connected = queue.Queue()
    pids, outcomes, workers = {}, {}, []

    def run(name, operation):
        announced = False
        try:
            close_old_connections()
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
                cursor.execute("SELECT pg_backend_pid()")
                pids[name] = cursor.fetchone()[0]
            connected.put((name, pids[name], None))
            announced = True
            outcomes[name] = (operation(), None)
        except Exception as exc:
            outcomes[name] = (None, exc)
            if not announced:
                connected.put((name, None, exc))
        finally:
            connections.close_all()

    def start(name, operation):
        worker = threading.Thread(target=run, args=(name, operation), daemon=True)
        workers.append((name, worker))
        worker.start()
        announced_name, pid, error = connected.get(timeout=5)
        assert announced_name == name
        if error is not None:
            raise error
        return pid

    try:
        first_pid = start("first", first)
        assert reached.wait(5), "First accept never reached its lock-held pause"
        second_pid = start("second", second)
        assert first_pid != second_pid, "Contenders must use separate PostgreSQL sessions"
        _wait_for_lock_edge(second_pid, first_pid)
    finally:
        release.set()
        deadline = time.monotonic() + 20
        for _, worker in workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        # Failed observations must not leave sessions holding locks in later tests.
        cleanup_errors = []
        for name, worker in workers:
            if worker.is_alive() and name in pids:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_terminate_backend(%s)", [pids[name]])
                except Exception as exc:
                    cleanup_errors.append(exc)
                finally:
                    worker.join(timeout=5)
        assert all(not worker.is_alive() for _, worker in workers), "Accept worker did not exit"
        if cleanup_errors:
            raise cleanup_errors[0]

    assert set(outcomes) == {"first", "second"}
    for _, error in outcomes.values():
        if error is not None:
            raise error
    return outcomes["first"][0], outcomes["second"][0], pids
