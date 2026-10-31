import logging
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar

from django.db import transaction
from django.utils import timezone

from apps.backup.not_restored import TenantNotRestored, assert_restored
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed, SourceMigrationGateUnavailable
from apps.tenant_migration.gate_locks import (
    _retained_shared_lock_keys, _reuse_shared_boundary, _unscoped_writer_owned,
    acquire_shared, exclusive_boundary, shared_boundary,
)
from apps.tenant_migration.models_source_gate import SourceMigrationGate


_archive_authority = ContextVar("source_migration_archive_authority", default=None)
_boundary_shared_locks = ContextVar("source_gate_boundary_shared_locks", default=())
_boundary_exclusive_owner = ContextVar("source_gate_boundary_exclusive_owner", default=None)
logger = logging.getLogger(__name__)


def assert_write_allowed(makerspace_id):
    """Lock and validate in either a service transaction or a gate boundary."""
    makerspace_id = int(makerspace_id)
    raw_shared = _reuse_shared_boundary(makerspace_id)
    if raw_shared or makerspace_id in _boundary_shared_locks.get():
        _assert_gate_state(makerspace_id)
        return
    if transaction.get_connection().in_atomic_block:
        acquire_shared(makerspace_id)
        _assert_gate_state(makerspace_id)
        return
    # A direct non-transactional assertion is supported for boundary-style callers.
    # Request/task boundaries use ``boundary_tenant_write`` so this same lock remains
    # held after validation and through their entire dispatch.
    with shared_boundary(makerspace_id):
        _assert_gate_state(makerspace_id)


def _assert_gate_state(makerspace_id):
    owner = _boundary_exclusive_owner.get()
    if owner is not None and owner[0] == makerspace_id:
        _exclusive_boundary_connection(makerspace_id)
    assert_restored(makerspace_id)
    from apps.makerspaces.purge_intent import assert_not_purging

    assert_not_purging(makerspace_id)
    gate = SourceMigrationGate.objects.only(
        "state", "purpose", "owner_id", "fencing_token", "lease_expires_at"
    ).filter(makerspace_id=makerspace_id).first()
    if gate is None or gate.state == SourceMigrationGate.State.OPEN:
        return
    authority = _archive_authority.get()
    if (
        authority == (int(makerspace_id), gate.owner_id, gate.fencing_token)
        and gate.lease_expires_at is not None
        and gate.lease_expires_at > timezone.now()
    ):
        return
    raise SourceMigrationGateClosed(
        "This makerspace is temporarily frozen for tenant migration.",
        purpose=gate.purpose,
    )


@contextmanager
def boundary_tenant_write(makerspace_id, *, exclusive=False):
    """Retain one real lock, reusing it through nested service/worker phases."""
    makerspace_id = int(makerspace_id)
    if exclusive:
        caller = transaction.get_connection()
        # Refuse BEFORE the retained-owner shortcut: a shared owner cannot upgrade,
        # and an application transaction cannot be carried across an operator scan.
        if (_retained_shared_lock_keys() or _boundary_shared_locks.get()
                or _boundary_exclusive_owner.get() is not None
                or _unscoped_writer_owned.get()
                or caller.in_atomic_block or not caller.get_autocommit()):
            raise SourceMigrationGateUnavailable(
                "Exclusive source boundary requires a top-level non-transactional caller."
            )
    raw_shared = _reuse_shared_boundary(makerspace_id)
    if makerspace_id in _boundary_shared_locks.get():
        _assert_gate_state(makerspace_id)
        yield
        return
    # An existing SQL transaction retains its own lock through its eventual commit.
    # Do not open a second connection behind a queued exclusive migration writer:
    # that would wait on the writer while the writer waits on our first shared lock.
    with ExitStack() as locks:
        if exclusive:
            owner = locks.enter_context(exclusive_boundary(makerspace_id))
            _assert_gate_state(makerspace_id)
        elif raw_shared:
            # The outer raw owner retains the same backend/transaction even if an
            # exclusive writer has queued; a second shared acquire can deadlock.
            _assert_gate_state(makerspace_id)
        elif transaction.get_connection().in_atomic_block:
            assert_write_allowed(makerspace_id)
        else:
            locks.enter_context(shared_boundary(makerspace_id))
            _assert_gate_state(makerspace_id)
        token = _boundary_shared_locks.set(_boundary_shared_locks.get() + (makerspace_id,))
        exclusive_token = _boundary_exclusive_owner.set((makerspace_id, owner)) if exclusive else None
        try:
            yield
        finally:
            if exclusive_token is not None:
                _boundary_exclusive_owner.reset(exclusive_token)
            _boundary_shared_locks.reset(token)


@contextmanager
def fanout_tenant_write(makerspace_id, *, operation, counts, exclusive=False):
    """Hold one tenant boundary, or report a frozen item and let the scan continue."""
    makerspace_id = int(makerspace_id)
    with ExitStack() as stack:
        try:
            stack.enter_context(boundary_tenant_write(makerspace_id, exclusive=exclusive))
        except (SourceMigrationGateClosed, TenantNotRestored):
            counts["skipped"] = counts.get("skipped", 0) + 1
            logger.info(
                "tenant_fanout_skipped_closed_source_gate",
                extra={"makerspace_id": makerspace_id, "operation": operation},
            )
            yield False
            return
        yield True


def _exclusive_boundary_connection(makerspace_id):
    """Private counter bridge: require the active matching owner and original backend."""
    makerspace_id = int(makerspace_id)
    owner = _boundary_exclusive_owner.get()
    if (owner is None or owner[0] != makerspace_id
            or makerspace_id not in _boundary_shared_locks.get()):
        raise SourceMigrationGateUnavailable("Counter commit requires its exclusive source owner.")
    return owner[1].verified_connection()


def assert_request_write_allowed(request):
    """Late DRF guard for tenants resolved only after parsing/authentication."""
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    from apps.makerspaces.origin_scope import origin_scoped_makerspace_id
    from apps.makerspaces.origin_scope_routes import authoritative_route_resolution
    from apps.tenant_migration.gate_policy import HTTP_EXEMPTIONS

    match = getattr(request, "resolver_match", None)
    from apps.tenant_migration.gate_http_ownership import api_owns_http_boundary

    if api_owns_http_boundary(request, match):
        if not _unscoped_writer_owned.get():
            raise SourceMigrationGateUnavailable(
                "The dedicated QR API boundary requires its unscoped writer lock."
            )
        return
    if getattr(match, "view_name", None) in HTTP_EXEMPTIONS:
        return
    targets, route_recognized = authoritative_route_resolution(request)
    if targets:
        # URL/model ownership is authoritative. Client hints are intentionally not
        # consulted here: a conflicting hint remains the view's validation error, but
        # cannot select a different tenant lock or bypass a closed source gate.
        for makerspace_id in sorted(targets):
            assert_write_allowed(makerspace_id)
        return
    if route_recognized:
        # Known-but-unresolvable routes are not tenant writes yet. Preserve the
        # eventual view error and rely on the unscoped request-boundary lock.
        return
    try:
        makerspace_id = origin_scoped_makerspace_id(request)
    except Exception:
        return
    if isinstance(makerspace_id, int):
        assert_write_allowed(makerspace_id)


@contextmanager
def tenant_write(makerspace_id):
    """Hold the shared advisory lock from validation through transaction commit."""
    with transaction.atomic():
        assert_write_allowed(makerspace_id)
        yield


@contextmanager
def source_archive_write(makerspace_id, owner_id, fencing_token):
    token = _archive_authority.set(
        (int(makerspace_id), owner_id, int(fencing_token))
    )
    try:
        with tenant_write(makerspace_id):
            yield
    finally:
        _archive_authority.reset(token)


@contextmanager
def source_archive_boundary(makerspace_id, owner_id, fencing_token):
    token = _archive_authority.set((int(makerspace_id), owner_id, int(fencing_token)))
    try:
        with boundary_tenant_write(makerspace_id):
            yield
    finally:
        _archive_authority.reset(token)


def assert_boundary_held(makerspace_id):
    """Raw storage writers may run only under a retained outer tenant boundary."""
    if int(makerspace_id) not in _boundary_shared_locks.get():
        from .gate_errors import SourceMigrationGateUnavailable

        raise SourceMigrationGateUnavailable("Raw export upload requires its tenant source boundary.")
    _reuse_shared_boundary(int(makerspace_id))
    _assert_gate_state(int(makerspace_id))
