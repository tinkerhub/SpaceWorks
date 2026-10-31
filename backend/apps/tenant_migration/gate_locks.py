from contextlib import contextmanager
from contextvars import ContextVar

import psycopg2
from django.db import connection, connections, transaction

from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable


# PostgreSQL advisory locks are keyed by a pair of signed int32 values. These values
# are deliberately outside the PII namespaces (734201/734202); the import fence uses
# the PII operation setting rather than this namespace.
SOURCE_GATE_LOCK_NAMESPACE = 734_310
UNSCOPED_WRITER_LOCK_KEY = 0
_unscoped_writer_owned = ContextVar("source_unscoped_writer_owned", default=False)
_retained_shared_locks = ContextVar("source_retained_shared_locks", default=())


def acquire_shared(makerspace_id):
    _execute_transaction("pg_advisory_xact_lock_shared", makerspace_id)


def acquire_exclusive(makerspace_id):
    _execute_transaction("pg_advisory_xact_lock", makerspace_id)


def acquire_unscoped_writer_shared():
    _execute_transaction(
        "pg_advisory_xact_lock_shared", UNSCOPED_WRITER_LOCK_KEY
    )


def acquire_unscoped_writer_exclusive():
    _execute_transaction("pg_advisory_xact_lock", UNSCOPED_WRITER_LOCK_KEY)


def try_acquire_exclusive(makerspace_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            [SOURCE_GATE_LOCK_NAMESPACE, int(makerspace_id)],
        )
        return bool(cursor.fetchone()[0])


def _execute_transaction(function, makerspace_id):
    if not connection.in_atomic_block:
        raise RuntimeError("Source migration locks require an atomic transaction.")
    _execute(function, makerspace_id)


def _execute(function, makerspace_id):
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {function}(%s, %s)",
            [SOURCE_GATE_LOCK_NAMESPACE, int(makerspace_id)],
        )


@contextmanager
def shared_boundary(makerspace_id):
    """Hold one shared-lock reference without transacting on the caller connection."""
    lock = _BoundarySharedLock(makerspace_id)
    try:
        lock.acquire()
        token = _retained_shared_locks.set(_retained_shared_locks.get() + (lock,))
        try:
            yield lock
        finally:
            _retained_shared_locks.reset(token)
    finally:
        lock.release()


def _retained_shared_lock_keys():
    """Read actual retained references, refusing even one lost reference."""
    for lock in _retained_shared_locks.get():
        lock.verify()
    return frozenset(lock.makerspace_id for lock in _retained_shared_locks.get())


def _reuse_shared_boundary(makerspace_id):
    """Verify every matching reference; a lost one must never trigger reacquisition."""
    matches = tuple(lock for lock in _retained_shared_locks.get()
                    if lock.makerspace_id == int(makerspace_id))
    for lock in matches:
        lock.verify()
    return bool(matches)


class _BoundarySharedLock:
    """One idempotent reference held by a dedicated lock-only transaction."""

    def __init__(self, makerspace_id):
        self.makerspace_id = int(makerspace_id)
        self.acquired = False
        self.lock_connection = None
        self.backend_pid = None
        self.transaction_id = None

    def acquire(self):
        if self.acquired:
            self.verify()
            return
        if self.backend_pid is not None:
            raise SourceMigrationGateUnavailable("Shared source boundary cannot reacquire its backend.")
        lock_connection = None
        try:
            lock_connection = _new_lock_connection()
            self.lock_connection = lock_connection
            lock_connection.autocommit = False
            with lock_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock_shared(%s, %s), pg_backend_pid(), pg_current_xact_id()",
                    [SOURCE_GATE_LOCK_NAMESPACE, self.makerspace_id],
                )
                _, self.backend_pid, self.transaction_id = cursor.fetchone()
            self._verify()
            self.acquired = True
        except Exception as exc:
            if lock_connection is not None:
                try:
                    lock_connection.close()
                except Exception:
                    pass
            self.lock_connection = None
            raise SourceMigrationGateUnavailable(
                "The source migration write gate is unavailable."
            ) from exc

    def verify(self):
        if not self.acquired:
            raise SourceMigrationGateUnavailable("The shared source boundary was released.")
        self._verify()

    def _verify(self):
        try:
            if self.lock_connection is None or self.lock_connection.closed or self.lock_connection.autocommit:
                raise RuntimeError("Shared source transaction ended.")
            with self.lock_connection.cursor() as cursor:
                cursor.execute(
                    """SELECT pg_backend_pid(), EXISTS (
                           SELECT 1 FROM pg_locks
                           WHERE locktype = 'advisory' AND pid = pg_backend_pid()
                             AND classid = %s AND objid = %s AND objsubid = 2
                             AND mode = 'ShareLock' AND granted
                       ), pg_current_xact_id()""",
                    [SOURCE_GATE_LOCK_NAMESPACE, self.makerspace_id],
                )
                pid, held, transaction_id = cursor.fetchone()
            if pid != self.backend_pid or transaction_id != self.transaction_id or not held:
                raise RuntimeError("Original shared source backend/transaction/lock was lost.")
        except Exception as exc:
            # Keep acquired intact: the original owner must still rollback/close.
            raise SourceMigrationGateUnavailable("The shared source boundary was lost.") from exc

    def release(self):
        if not self.acquired:
            return
        lock_connection = self.lock_connection
        release_error = None
        try:
            lock_connection.rollback()
        except Exception as exc:
            release_error = exc
        try:
            lock_connection.close()
        except Exception as exc:
            release_error = release_error or exc
        finally:
            self.lock_connection = None
            self.acquired = False
        if release_error is not None:
            raise SourceMigrationGateUnavailable(
                "The source migration write gate could not be released safely."
            ) from release_error


def _new_lock_connection():
    # Bypass Django's connection lifecycle: this transaction exists only to pin
    # one PostgreSQL backend and hold the source-gate advisory lock. Each call
    # must return a distinct connection so nested boundaries remain independent.
    params = connections["default"].get_connection_params()
    return psycopg2.connect(**params)


@contextmanager
def exclusive_boundary(makerspace_id):
    """Operator-only owner; never reconnect or reacquire after continuity loss."""
    lock = _BoundaryExclusiveLock(makerspace_id)
    try:
        lock.acquire()
        yield lock
    finally:
        lock.acquired = False
        if lock.lock_connection is not None:
            # Preserve the original failure, especially an uncertain commit ACK.
            try:
                lock.lock_connection.rollback()
            except Exception:
                pass
            try:
                lock.lock_connection.close()
            except Exception:
                pass


class _BoundaryExclusiveLock:
    def __init__(self, makerspace_id):
        if type(makerspace_id) is not int or not 0 < makerspace_id <= 2147483647:
            raise SourceMigrationGateUnavailable("Exclusive boundary requires a bounded tenant ID.")
        self.makerspace_id = makerspace_id
        self.lock_connection = None
        self.backend_pid = None
        self.transaction_id = None
        self.acquired = False

    def acquire(self):
        if self.lock_connection is not None:
            raise SourceMigrationGateUnavailable("Exclusive boundary cannot reacquire its backend.")
        try:
            self.lock_connection = _new_lock_connection()
            self.lock_connection.autocommit = False
            with self.lock_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s, %s), pg_backend_pid(), pg_current_xact_id()",
                    [SOURCE_GATE_LOCK_NAMESPACE, self.makerspace_id],
                )
                _, self.backend_pid, self.transaction_id = cursor.fetchone()
            self._verify()
            self.acquired = True
        except Exception as exc:
            raise SourceMigrationGateUnavailable("The exclusive source boundary is unavailable.") from exc

    def verified_connection(self):
        if not self.acquired:
            raise SourceMigrationGateUnavailable("No acquired exclusive source boundary.")
        self._verify()
        return self.lock_connection

    def _verify(self):
        try:
            if self.lock_connection.closed or self.lock_connection.autocommit:
                raise RuntimeError("Exclusive source transaction ended.")
            with self.lock_connection.cursor() as cursor:
                cursor.execute(
                    """SELECT pg_backend_pid(), EXISTS (
                           SELECT 1 FROM pg_locks
                           WHERE locktype = 'advisory' AND pid = pg_backend_pid()
                             AND classid = %s AND objid = %s AND objsubid = 2
                             AND mode = 'ExclusiveLock' AND granted
                       ), pg_current_xact_id()""",
                    [SOURCE_GATE_LOCK_NAMESPACE, self.makerspace_id],
                )
                pid, held, transaction_id = cursor.fetchone()
            if pid != self.backend_pid or transaction_id != self.transaction_id or not held:
                raise RuntimeError("Original exclusive source backend/transaction/lock was lost.")
        except Exception as exc:
            self.acquired = False
            raise SourceMigrationGateUnavailable("The exclusive source boundary was lost.") from exc


@contextmanager
def unscoped_writer_shared_boundary():
    if _unscoped_writer_owned.get():
        yield
        return
    with shared_boundary(UNSCOPED_WRITER_LOCK_KEY):
        token = _unscoped_writer_owned.set(True)
        try:
            yield
        finally:
            _unscoped_writer_owned.reset(token)


@contextmanager
def shared_transaction(makerspace_id):
    with transaction.atomic():
        acquire_shared(makerspace_id)
        yield
