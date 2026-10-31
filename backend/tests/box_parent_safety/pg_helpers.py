"""Observe real SQL and PostgreSQL wait edges without replacing any lock code."""
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

from django.db import close_old_connections, connection, connections


@dataclass
class Statement:
    sql: str
    params: tuple
    pid: int
    completed: bool = False


def maker_lock(statement):
    return ('FROM "makerspaces_makerspace"' in statement.sql
            and 'FOR ' in statement.sql)


def assert_maker_mode(statement, clause):
    assert maker_lock(statement), statement
    # An exact suffix distinguishes UPDATE from NO KEY UPDATE and forbids NOWAIT.
    assert statement.sql.rstrip().endswith(clause), statement


class Worker:
    def __init__(self, operation, *, pause=None):
        self.operation, self.pause = operation, pause
        self.ready, self.reached, self.release = (threading.Event() for _ in range(3))
        self.statements, self.pid, self.result, self.error = [], None, None, None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        try:
            close_old_connections()
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                self.pid = cursor.fetchone()[0]
            self.ready.set()
            with connection.execute_wrapper(self.capture):
                self.result = self.operation()
        except BaseException as exc:
            self.error = exc
        finally:
            self.ready.set()
            connections.close_all()

    def capture(self, execute, sql, params, many, context):
        statement = Statement(sql, tuple(params or ()), self.pid)
        self.statements.append(statement)  # full SQL, including a wide Maker SELECT
        result = execute(sql, params, many, context)
        statement.completed = True
        if self.pause and not self.reached.is_set() and self.pause(statement):
            self.reached.set()  # the real statement succeeded and its lock is held
            assert self.release.wait(20), "Controller did not release SQL observation pause"
        return result

    def start(self):
        self.thread.start()
        assert self.ready.wait(10), "Worker did not connect"
        if self.error:
            raise self.error
        return self

    def paused(self):
        assert self.reached.wait(10), (self.error, self.statements)
        assert self.error is None

    def finish(self):
        self.release.set()
        self.thread.join(20)
        assert not self.thread.is_alive(), "Owned worker did not finish"
        if self.error:
            raise self.error
        return self.result


@contextmanager
def workers():
    """Always release pauses; terminate only a stuck backend owned by this test."""
    assert connection.vendor == "postgresql", "Real PostgreSQL is required"
    assert connection.get_autocommit() and not connection.in_atomic_block
    owned = []

    def start(operation, *, pause=None):
        worker = Worker(operation, pause=pause)
        owned.append(worker)
        return worker.start()

    try:
        yield start
    finally:
        for worker in owned:
            worker.release.set()
        for worker in owned:
            worker.thread.join(20)
            if worker.thread.is_alive() and worker.pid:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_terminate_backend(%s)", [worker.pid])
                worker.thread.join(5)
            assert not worker.thread.is_alive(), "Owned PostgreSQL worker leaked"


def blocked_by(worker, blocker_pid, predicate=maker_lock):
    """Bind a full in-thread statement to an exact PID -> blocking PID edge.

    pg_stat_activity.query is intentionally unused: track_activity_query_size can
    truncate the Maker SELECT before its FROM/lock clause. No DB timeout is set.
    The deadline is only a failed-observation watchdog, never evidence of a lock.
    """
    deadline = time.monotonic() + 10
    poll = threading.Event()
    while time.monotonic() < deadline:
        if worker.error:
            raise worker.error
        pending = [s for s in worker.statements if not s.completed and predicate(s)]
        if pending:
            statement = pending[-1]
            assert statement.pid == worker.pid != blocker_pid
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_blocking_pids(%s)", [worker.pid])
                blockers = cursor.fetchone()[0]
            if blocker_pid in blockers:
                assert not statement.completed, statement
                return statement
        poll.wait(0.01)
    raise AssertionError(("No real PostgreSQL wait edge", worker.pid,
                          blocker_pid, worker.statements, worker.error))
