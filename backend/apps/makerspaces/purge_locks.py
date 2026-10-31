"""Dedicated lock-only exclusion across short application commits and remote I/O."""

from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import connection

from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.not_restored import active_component_states, assert_restored
from apps.backup.operation_lock import deployment_operation_lock
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE, _new_lock_connection


class PurgeBusy(ValidationError):
    pass


_retained_boundary = ContextVar("retained_exclusive_purge_boundary", default=None)


def assert_cleanup_boundary(makerspace_id, verify):
    retained = _retained_boundary.get()
    if retained is None or retained[0] is not verify or makerspace_id not in retained[1]:
        raise SourceMigrationGateUnavailable("Synchronous cleanup requires the actual retained exclusive purge owner.")
    verify()


@contextmanager
def purge_boundary(makerspace_id, *, all_tenants=False):
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValidationError("Purge requires a non-transactional caller.")
    if type(makerspace_id) is not int or not 0 < makerspace_id <= 2147483647:
        raise ValidationError("Purge requires a bounded makerspace lock identity.")
    from .models import Makerspace

    with deployment_operation_lock(blocking=False):
        lock = None
        try:
            lock = _new_lock_connection()
            lock.autocommit = False
            keys = [0]
            with lock.cursor() as cursor:
                # Unscoped exclusion comes first, including unknown/new tenants.
                pid = _try_lock(cursor, 0)
                inventory = tuple(Makerspace._base_manager.order_by("pk").values_list("pk", flat=True)) if all_tenants else ()
                if any(type(key) is not int or not 0 < key <= 2147483647 for key in inventory):
                    raise ValidationError("Maker inventory contains an unsupported source lock identity.")
                keys.extend(sorted(set(inventory) | {int(makerspace_id)}))
                for key in keys[1:]:
                    if _try_lock(cursor, key) != pid:
                        raise SourceMigrationGateUnavailable("The purge lock backend changed.")
            def verify():
                _verify_retained(lock, pid, keys)
                if all_tenants and tuple(Makerspace._base_manager.order_by("pk").values_list("pk", flat=True)) != inventory:
                    raise PurgeBusy("Maker inventory changed; retry cleanup before deleting bytes.")
            verify()
            assert_recovery_allowed(None if all_tenants else makerspace_id)
            token = _retained_boundary.set((verify, frozenset(keys[1:])))
            try:
                yield verify
            finally:
                _retained_boundary.reset(token)
        finally:
            if lock is not None:
                try:
                    lock.rollback()
                finally:
                    lock.close()


def _try_lock(cursor, key):
    cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s), pg_backend_pid()",
                   [SOURCE_GATE_LOCK_NAMESPACE, int(key)])
    acquired, pid = cursor.fetchone()
    if not acquired:
        raise PurgeBusy("A source writer or deployment operation is busy; retry later.")
    return pid


def _verify_retained(lock, pid, keys):
    try:
        with lock.cursor() as cursor:
            cursor.execute(
                """SELECT pg_backend_pid(), count(*) FROM pg_locks
                   WHERE locktype='advisory' AND pid=pg_backend_pid()
                     AND classid=%s AND objid = ANY(%s) AND objsubid=2
                     AND mode='ExclusiveLock' AND granted""",
                [SOURCE_GATE_LOCK_NAMESPACE, keys],
            )
            current_pid, count = cursor.fetchone()
        if current_pid != pid or count != len(keys):
            raise RuntimeError("Exclusive purge source locks were not retained.")
    except Exception as exc:
        raise SourceMigrationGateUnavailable("The exclusive purge source boundary was lost.") from exc


def assert_recovery_allowed(makerspace_id=None):
    state = DeploymentRecoveryState.objects.filter(pk=1).first()
    if state is None or state.mode != DeploymentRecoveryState.Mode.NORMAL:
        raise ValidationError("Deployment recovery or restore state refuses purge.")
    if active_component_states().exists():
        raise ValidationError("Unrestored tenant components prevent a complete purge ownership proof.")
    terminal = {
        RestoreOperation.Stage.COMPLETED, RestoreOperation.Stage.FAILED,
        RestoreOperation.Stage.ABORTED, RestoreOperation.Stage.RESTORED_QUARANTINED,
    }
    # Successful quarantine acknowledgement retains the FK for provenance.
    if RestoreOperation.objects.exclude(stage__in=terminal).exists():
        raise ValidationError("An ongoing restore prevents purge.")
    if makerspace_id is not None:
        assert_restored(makerspace_id)
    return state
