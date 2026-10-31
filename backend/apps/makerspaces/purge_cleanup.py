"""Suppress duplicate object callbacks only during synchronous graph ownership."""

from contextlib import contextmanager
from contextvars import ContextVar

from .purge_locks import assert_cleanup_boundary


_owned_tenant = ContextVar("synchronous_purge_cleanup_owner", default=None)


def owns_cleanup(makerspace_id):
    owner = _owned_tenant.get()
    if owner is None or owner[0] != makerspace_id:
        return False
    assert_cleanup_boundary(makerspace_id, owner[1])
    return True


@contextmanager
def synchronous_cleanup(makerspace_id, *, verify):
    assert_cleanup_boundary(makerspace_id, verify)
    token = _owned_tenant.set((int(makerspace_id), verify))
    try:
        yield
    finally:
        _owned_tenant.reset(token)
