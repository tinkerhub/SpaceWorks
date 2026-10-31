"""Observation only: retain the entire production middleware and real dispatch."""
import threading
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connection

from apps.tenant_migration.gate_locks import _unscoped_writer_owned

_active_probe = ContextVar("qr_http_test_dispatch_probe", default=None)


class Checkpoint:
    def __init__(self):
        self.reached, self.release = threading.Event(), threading.Event()
        self.context_owned = None

    def stop(self):
        self.context_owned = _unscoped_writer_owned.get()
        self.reached.set()
        assert self.release.wait(20), "Controller did not release observation checkpoint"

    def wait(self, worker):
        assert self.reached.wait(10), (worker.error, worker.statements)
        assert worker.error is None
        assert self.context_owned is True


class DispatchProbe:
    def __init__(self, update_table):
        self.enter, self.update, self.audit, self.tail = (Checkpoint() for _ in range(4))
        self.update_table = update_table
        self.completed_sql = []

    def capture(self, execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        self.completed_sql.append({
            "sql": sql, "params": tuple(params or ()), "completed": True,
            "pid": context["connection"].connection.info.backend_pid,
        })
        if sql.startswith(f'UPDATE "{self.update_table}"') and not self.update.reached.is_set():
            self.update.stop()  # The real UPDATE has completed, not an attempted write.
        elif sql.startswith('INSERT INTO "audit_auditlog"') and not self.audit.reached.is_set():
            self.audit.stop()  # The real INSERT has completed inside the service transaction.
        return result

    def run(self, operation):
        def observed():
            token = _active_probe.set(self)
            try:
                with connection.execute_wrapper(self.capture):
                    return operation()
            finally:
                _active_probe.reset(token)
        return observed


class ObserveDelegatedDispatchMiddleware:
    """Inserted immediately INSIDE the unchanged SourceMigrationGateMiddleware."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        probe = _active_probe.get()
        if probe:
            probe.enter.stop()
        response = self.get_response(request)
        if probe:
            probe.tail.stop()
        return response


@contextmanager
def observe_dispatch(settings, update_table):
    middleware = list(settings.MIDDLEWARE)
    index = middleware.index("apps.tenant_migration.middleware.SourceMigrationGateMiddleware")
    settings.MIDDLEWARE = [
        *middleware[:index + 1],
        "tests.qr_http_ownership_safety.dispatch_probe.ObserveDelegatedDispatchMiddleware",
        *middleware[index + 1:],
    ]
    probe = DispatchProbe(update_table)
    try:
        yield probe
    finally:
        for step in (probe.enter, probe.update, probe.audit, probe.tail):
            step.release.set()
        settings.MIDDLEWARE = middleware
