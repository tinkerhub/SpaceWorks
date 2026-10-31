"""AssetQr-only HTTP proofs: real source locks, refusal, audit and outer commit."""
import pytest
from django.db import connection, transaction

from apps.tenant_migration.gate_locks import (
    SOURCE_GATE_LOCK_NAMESPACE, acquire_exclusive, try_acquire_exclusive,
)
from tests.box_parent_safety.pg_helpers import blocked_by, maker_lock, workers
from tests.qr_asset_race_safety.helpers import (
    assert_created, assert_lock_order, assert_no_domain_write, asset_http, asset_lock, audit_insert,
    backend_pid, code, dto, lab, qr_lock, record_sql, source_shared, state,
)
from tests.qr_asset_race_safety.source_observations import (
    assert_source_shared_held, dedicated_waiter, source_pids,
)
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("existing", [False, True], ids=["create", "reuse"])
def test_genuine_quiesced_source_returns_typed_423_without_mutation(lab, existing):
    if existing:
        code(lab)
    close_gate(lab.home, lab.mover)
    before = state()
    response = asset_http(lab)
    assert response.status_code == 423
    assert response.json() == {
        "detail": "This makerspace is temporarily frozen for tenant migration.",
        "code": "tenant_migration_quiesced", "purpose": "migration",
    }
    assert state() == before


def test_exclusive_source_blocks_http_before_any_domain_row_lock(lab, record_property):
    qr = code(lab)
    before, expected_dto = state(), dto(qr)

    def request_in_outer_atomic():
        with transaction.atomic():
            return asset_http(lab)

    with workers() as start:
        with transaction.atomic():
            acquire_exclusive(lab.home.pk)
            owner = backend_pid()
            api = start(request_in_outer_atomic)
            pending = blocked_by(api, owner, source_shared)
            assert pending.params == (SOURCE_GATE_LOCK_NAMESPACE, lab.home.pk)
            assert not any(maker_lock(s) or qr_lock(s) or asset_lock(s) for s in api.statements)
            assert_no_domain_write(api.statements)
            assert state() == before
            record_property("source_wait", repr({"waiter": api.pid, "blocker": owner,
                                                 "sql": pending.sql, "params": pending.params}))
        response = api.finish()
    assert response.status_code == 201, response.data
    assert response.data == expected_dto
    assert state() == before
    assert_lock_order(api)
    record_sql(record_property, api, "asset_qr_full_sql")
    assert api.statements.index(pending) < next(
        i for i, statement in enumerate(api.statements) if maker_lock(statement))


@pytest.mark.parametrize("cut", ["audit-insert", "before-outer-commit"])
def test_shared_source_survives_real_audit_insert_and_outer_commit(lab, cut, record_property):
    before = state()
    marker = "SELECT 1 AS asset_qr_outer_commit_probe"

    def request_in_outer_atomic():
        with transaction.atomic():
            response = asset_http(lab)
            assert response.status_code == 201, response.data
            if cut == "before-outer-commit":
                with connection.cursor() as cursor:
                    cursor.execute(marker)
            return response

    pause = audit_insert if cut == "audit-insert" else lambda s: s.sql == marker
    with workers() as start:
        api = start(request_in_outer_atomic, pause=pause)
        api.paused()
        assert_source_shared_held(api.pid, lab.home.pk)
        with transaction.atomic():
            assert try_acquire_exclusive(lab.home.pk) is False
        assert state() == before  # QR + real audit INSERT are still uncommitted
        inserts = [s for s in api.statements if audit_insert(s)]
        assert len(inserts) == 1 and inserts[0].completed
        assert "qr.created" in inserts[0].params
        shared = next(s for s in api.statements if source_shared(s))
        assert shared.params == (SOURCE_GATE_LOCK_NAMESPACE, lab.home.pk)
        assert api.statements.index(shared) < next(
            i for i, statement in enumerate(api.statements) if maker_lock(statement))
        assert_lock_order(api, existing=False)
        record_property("source_lifetime", repr({"pid": api.pid, "cut": cut,
                                                 "source_sql": shared.sql,
                                                 "audit_sql": inserts[0].sql}))
        response = api.finish()
    assert_created(lab, before, response)
    record_sql(record_property, api, "asset_qr_full_sql")
    with transaction.atomic():
        assert try_acquire_exclusive(lab.home.pk) is True


def test_actual_dedicated_lock_acquisition_failure_is_typed_503(lab, record_property):
    before = state()
    # Cancel only the new backend waiting on this test's exact tenant key. This
    # makes PostgreSQL fail the real acquisition; no gate/lock function is mocked.
    with workers() as start:
        with transaction.atomic():
            acquire_exclusive(lab.home.pk)
            owner, previous = backend_pid(), source_pids(lab.home.pk)
            api = start(lambda: asset_http(lab))  # ordinary non-atomic HTTP caller
            pid, sql, blockers = dedicated_waiter(api, owner, lab.home.pk, previous)
            assert not any(maker_lock(s) or qr_lock(s) or asset_lock(s) for s in api.statements)
            assert state() == before
            record_property("cancelled_owned_source_wait", repr({
                "pid": pid, "sql": sql, "blocking_pids": blockers,
                "namespace": SOURCE_GATE_LOCK_NAMESPACE, "key": lab.home.pk,
            }))
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_cancel_backend(%s)", [pid])
                assert cursor.fetchone()[0] is True
            response = api.finish()
    assert response.status_code == 503
    assert response.json() == {
        "detail": "The source migration write gate is unavailable.",
        "code": "tenant_migration_gate_unavailable",
    }
    assert_no_domain_write(api.statements)
    assert state() == before
    assert source_pids(lab.home.pk) == set()
