"""Real source exclusives block dispatch; admission survives Audit INSERT and commit."""
import threading

import pytest
from django.db import transaction

from tests.qr_source_safety.http_helpers import (
    CROSS_WRITERS, WRITERS, closure_lab, prepared, success,
)
from tests.qr_source_safety.pg_helpers import (
    assert_shared, atomic_request, audit_insert, exclusive, row_lock, source_select,
    source_wait, try_exclusive, workers,
)
from tests.qr_source_safety.state_helpers import assert_gate, state
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", WRITERS)
def test_exclusive_source_blocks_actual_http_before_any_domain_row_lock(closure_lab, kind):
    case = prepared(closure_lab, kind)
    with workers() as start:
        with exclusive(closure_lab.home.pk) as owner:
            pending = start(atomic_request(case.call))
            source_wait(pending, owner, closure_lab.home.pk)
            close_gate(closure_lab.home, closure_lab.root)
            before = state()
        assert_gate(pending.finish())
    assert state() == before


@pytest.mark.parametrize("kind", (*WRITERS, "native-cross-product", "native-cross-asset"))
def test_real_audit_insert_and_actual_outer_commit_retain_source_n(closure_lab, kind):
    case = prepared(closure_lab, kind)
    tenant_ids = sorted({closure_lab.home.pk, *(
        [closure_lab.other.pk] if "cross" in kind else [])})
    returned, commit = threading.Event(), threading.Event()
    observed = {}

    def outer():
        with transaction.atomic():
            response = case.call()
            observed["response"] = response
            returned.set()
            assert commit.wait(20), "Controller did not allow real outer commit"
        return response

    with workers() as start:
        pending = start(outer, pause=audit_insert)
        try:
            pending.paused()  # Real INSERT has succeeded inside application atomic.
            assert any(audit_insert(sql) and sql.completed for sql in pending.statements)
            first_row = next(i for i, sql in enumerate(pending.statements) if row_lock(sql))
            for tenant_id in tenant_ids:
                admitted = [i for i, sql in enumerate(pending.statements)
                            if source_select(sql, tenant_id)]
                assert admitted and min(admitted) < first_row
                assert_shared(pending.pid, tenant_id)
                assert try_exclusive(tenant_id) is False
            if "cross" in kind:
                sequence = [tenant_id for sql in pending.statements[:first_row]
                            for tenant_id in tenant_ids if source_select(sql, tenant_id)]
                assert list(dict.fromkeys(sequence)) == tenant_ids
            pending.release.set()
            assert returned.wait(10), (pending.error, pending.statements)
            assert observed["response"].status_code == success(kind)
            if kind.endswith(("revoke", "rebind", "cross-product", "cross-asset")):
                assert not any('FROM "makerspaces_makerspace"' in sql.sql
                               and "FOR " in sql.sql for sql in pending.statements)
            for tenant_id in tenant_ids:
                assert_shared(pending.pid, tenant_id)
                assert try_exclusive(tenant_id) is False
        finally:
            commit.set()
        pending.finish()
    for tenant_id in tenant_ids:
        assert try_exclusive(tenant_id) is True


@pytest.mark.parametrize("kind", CROSS_WRITERS)
def test_sorted_two_source_admission_waits_at_destination_before_qr_lock(closure_lab, kind):
    # Reverse source/destination so sorted order is observable rather than incidental.
    closure_lab.home, closure_lab.other = closure_lab.other, closure_lab.home
    case = prepared(closure_lab, kind)
    low, high = sorted([closure_lab.home.pk, closure_lab.other.pk])
    with workers() as start:
        with exclusive(high) as owner:
            pending = start(atomic_request(case.call))
            source_wait(pending, owner, high)
            assert_shared(pending.pid, low)
            assert [sql.params[1] for sql in pending.statements
                    if "pg_advisory_xact_lock_shared" in sql.sql
                    and sql.params[1] in {low, high}] == [low, high]
            close_gate(closure_lab.home, closure_lab.root)
            before = state()
        assert_gate(pending.finish())
    assert state() == before
