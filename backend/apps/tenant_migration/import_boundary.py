"""Concrete shared publication fence for task-exempt target import services."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from .gate_locks import unscoped_writer_shared_boundary

_owned = ContextVar("tenant_import_unscoped_boundary", default=False)


@contextmanager
def import_write_boundary():
    if _owned.get():
        yield
        return
    with unscoped_writer_shared_boundary():
        token = _owned.set(True)
        try:
            yield
        finally:
            _owned.reset(token)


def import_writer(function):
    @wraps(function)
    def fenced(*args, **kwargs):
        with import_write_boundary():
            return function(*args, **kwargs)
    return fenced


def assert_import_boundary():
    if not _owned.get():
        raise RuntimeError("Raw import storage requires a service-owned publication boundary.")
