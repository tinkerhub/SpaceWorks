"""Source N precedes Maker and survives every nested HTTP atomic to outer commit."""
import threading

import pytest
from django.db import connection, transaction

from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE
from tests.box_parent_safety.http_helpers import (
    CREATORS, WRITERS, box, deletion, lab, success, writer,
)
from tests.box_parent_safety.pg_helpers import maker_lock, workers

pytestmark = pytest.mark.django_db(transaction=True)


def try_exclusive(tenant_id):
    # Roll back even a successful try-lock: observation never freezes a later phase.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s)",
                           [SOURCE_GATE_LOCK_NAMESPACE, tenant_id])
            acquired = cursor.fetchone()[0]
        transaction.set_rollback(True)
    return acquired


def source_select(statement, tenant_id):
    return ("pg_advisory_xact_lock_shared" in statement.sql
            and statement.params == (SOURCE_GATE_LOCK_NAMESPACE, tenant_id))


@pytest.mark.parametrize("kind", [*WRITERS, "single", "bulk"])
def test_source_admission_before_maker_is_retained_to_outer_commit(lab, kind):
    parent = box(lab.home, "Outer parent")
    child = None if kind in CREATORS else box(lab.home, "Outer child")
    operation = (deletion(lab.client, [parent], kind) if kind in {"single", "bulk"}
                 else writer(lab, kind, parent, child))
    returned, commit = threading.Event(), threading.Event()
    evidence = {}

    def outer_transaction():
        with transaction.atomic():
            response = operation()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = pg_backend_pid() "
                    "AND locktype = 'advisory' AND classid = %s AND objid = %s "
                    "AND objsubid = 2 AND mode = 'ShareLock' AND granted)",
                    [SOURCE_GATE_LOCK_NAMESPACE, lab.home.pk],
                )
                evidence["held_after_http"] = cursor.fetchone()[0]
            evidence["response"] = response
            returned.set()
            assert commit.wait(20), "Controller did not allow outer transaction commit"
        return response

    with workers() as start:
        pending = start(outer_transaction, pause=maker_lock)
        try:
            pending.paused()
            first_maker = next(i for i, s in enumerate(pending.statements) if maker_lock(s))
            admitted = [i for i, s in enumerate(pending.statements)
                        if source_select(s, lab.home.pk)]
            assert admitted and max(admitted) < first_maker
            assert try_exclusive(lab.home.pk) is False
            pending.release.set()
            assert returned.wait(10), (pending.error, pending.statements)
            assert evidence["response"].status_code == (302 if kind in {"single", "bulk"} else success(kind))
            assert evidence["held_after_http"] is True
            # HTTP and nested service/form/collector transactions have all exited;
            # only the caller's outer transaction is left holding Source N + Maker.
            assert try_exclusive(lab.home.pk) is False
            assert not any(source_select(s, lab.home.pk)
                           for s in pending.statements[first_maker + 1:])
        finally:
            commit.set()
        pending.finish()
    assert try_exclusive(lab.home.pk) is True
