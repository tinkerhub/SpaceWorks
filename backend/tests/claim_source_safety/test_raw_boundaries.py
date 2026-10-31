"""Public raw/shared entry points must prove reuse and reject lost ownership."""
import json

import pytest
from django.db import connection, transaction

from apps.accounts.claim_transition_gate import claim_transition_gate
from apps.audit import services as audit
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_locks import shared_boundary
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from tests.box_parent_safety.pg_helpers import workers
from tests.qr_http_ownership_safety.p_observations import identity, source_locks

from .observations import Checkpoint, NProof, exclusive_n, source_statement, wait_raw_n
from .state import domain, frozen, tenant_and_transition_audits

pytestmark = pytest.mark.django_db(transaction=True)


def test_raw_same_key_reuses_original_reference_despite_queued_exclusive(
    claim_lab, record_property,
):
    key = claim_lab.spaces[0].pk
    raw, committed = Checkpoint(), Checkpoint()
    proof = NProof([key], record_property)

    def operation():
        with shared_boundary(key):
            raw.stop()
            with boundary_tenant_write(key), transaction.atomic():
                audit.record(claim_lab.actor, "test.claim_source_raw", makerspace=claim_lab.spaces[0])
                connection.on_commit(committed.stop)
        return "same-key committed"

    def actual_audit(statement):
        return statement.sql.startswith('INSERT INTO "audit_auditlog"')

    with workers() as start:
        try:
            request = start(operation, pause=actual_audit)
            raw.wait(request)
            proof.observe("raw_shared_owner")
            exclusive = start(lambda: exclusive_n(key))
            proof.queued(exclusive, key)
            raw.release.set()
            request.paused()
            proof.observe("raw_reuse_actual_audit_INSERT")
            proof.queued(exclusive, key)
            request.release.set()
            committed.wait(request)
            proof.observe("raw_reuse_real_commit")
            proof.queued(exclusive, key)
            committed.release.set()
            assert request.finish() == "same-key committed"
            assert exclusive.finish() == "exclusive N acquired"
            record_property("raw_reuse_full_SQL", json.dumps([vars(s) for s in request.statements], default=str))
        finally:
            raw.release.set()
            committed.release.set()
    proof.released()


def test_genuinely_new_lower_n_refused_before_any_acquisition_or_identity_row_lock(
    claim_lab, record_property,
):
    lower, held = claim_lab.spaces
    assert lower.pk < held.pk
    proof = NProof([held.pk], record_property)
    before, audits = domain(), tenant_and_transition_audits()
    raw = Checkpoint()

    def operation():
        with shared_boundary(held.pk):
            raw.stop()
            with pytest.raises(SourceMigrationGateUnavailable):
                with claim_transition_gate(claim_lab.user.pk):
                    pytest.fail("New lower tenant was admitted under an existing higher raw N")
            proof.observe("higher_raw_owner_after_lower_refusal")
        return "lower refused before acquisition"

    with workers() as start:
        try:
            blocker = start(lambda: exclusive_n(lower.pk), pause=source_statement)
            blocker.paused()
            request = start(operation)
            raw.wait(request)
            proof.observe("higher_raw_owner")
            raw.release.set()
            # The lower exclusive stays held until the refusal returns. Thus a
            # mistaken attempt at a new lower raw N cannot silently pass.
            assert request.finish() == "lower refused before acquisition"
            assert not [row for row in source_locks() if row["objid"] == lower.pk
                        and row["mode"] == "ShareLock"]
            blocker.finish()
        finally:
            raw.release.set()
    proof.released()
    assert domain() == before
    assert tenant_and_transition_audits() == audits


@pytest.mark.parametrize("loss", ["connection", "transaction"])
def test_actual_raw_owner_loss_is_strict_unavailable_without_reconnect_or_writes(
    claim_lab, loss, record_property,
):
    key = claim_lab.spaces[0].pk
    before, audits = domain(), tenant_and_transition_audits()
    body_checked = False
    # The yielded public boundary reference already exposes its own connection;
    # never manufacture a PID or alter any source-guard predicate.
    try:
        with shared_boundary(key) as owner:
            proof = NProof([key], record_property)
            pid = proof.observe("raw_before_actual_loss")[key]
            if loss == "connection":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
                    assert cursor.fetchone()[0]
            else:
                owner.lock_connection.rollback()
            with pytest.raises(SourceMigrationGateUnavailable):
                with boundary_tenant_write(key):
                    pytest.fail("A lost raw reference must not reconnect or enter the body")
            body_checked = True
            assert not [row for row in source_locks() if row["objid"] == key and row["granted"]]
    except SourceMigrationGateUnavailable:
        # Loss may also be detected while releasing a terminated connection.
        assert body_checked
    assert body_checked
    assert domain() == before
    assert tenant_and_transition_audits() == audits


def test_p_key_zero_is_not_tenant_admission(claim_lab, record_property):
    key = claim_lab.spaces[0].pk
    raw = Checkpoint()

    def operation():
        with shared_boundary(0):
            raw.stop()
            with boundary_tenant_write(key):
                return "tenant separately admitted"

    with workers() as start:
        try:
            blocker = start(lambda: exclusive_n(key), pause=source_statement)
            blocker.paused()
            request = start(operation)
            raw.wait(request)
            baseline = {identity(row) for row in source_locks()}
            assert not [row for row in source_locks() if row["objid"] == key and row["mode"] == "ShareLock"]
            raw.release.set()
            wait_raw_n(key, blocker.pid, baseline, record_property)
            blocker.finish()
            assert request.finish() == "tenant separately admitted"
        finally:
            raw.release.set()


def test_raw_same_key_reuse_still_checks_fresh_quiesced_state(claim_lab):
    key = claim_lab.spaces[0].pk
    before = domain()
    with shared_boundary(key):
        frozen(claim_lab.spaces[0], claim_lab.actor)
        from apps.tenant_migration.gate_errors import SourceMigrationGateClosed

        with pytest.raises(SourceMigrationGateClosed):
            with boundary_tenant_write(key):
                pytest.fail("Retained lock does not bypass a fresh source-state check")
    assert domain() == before


@pytest.mark.parametrize("key", [0, "actualMaker"])
def test_retained_raw_shared_owner_refuses_exclusive_upgrade(claim_lab, key, monkeypatch):
    from unittest.mock import Mock

    from apps.tenant_migration import gate_locks

    actual_maker = claim_lab.spaces[0].pk
    key = actual_maker if key == "actualMaker" else key
    assert not connection.in_atomic_block and connection.get_autocommit()
    before, audits = domain(), tenant_and_transition_audits()
    baseline_locks = {identity(row) for row in source_locks()}
    baseline_refs = gate_locks._retained_shared_locks.get()
    factory = Mock(wraps=gate_locks._new_lock_connection)
    monkeypatch.setattr(gate_locks, "_new_lock_connection", factory)

    with shared_boundary(key) as owner:
        original_connection = owner.lock_connection
        original_pid, original_xid = owner.backend_pid, owner.transaction_id
        original_locks = None
        for checkpoint in ("before_refusal", "after_refusal"):
            if checkpoint == "after_refusal":
                with pytest.raises(SourceMigrationGateUnavailable):
                    with boundary_tenant_write(actual_maker, exclusive=True):
                        pytest.fail("A retained raw shared owner must forbid exclusive upgrade")
            owner.verify()
            assert owner.acquired and owner.lock_connection is original_connection
            assert (owner.backend_pid, owner.transaction_id) == (original_pid, original_xid)
            with original_connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid(), pg_current_xact_id()")
                assert cursor.fetchone() == (original_pid, original_xid)
            rows = source_locks()
            owned = [row for row in rows if row["pid"] == original_pid]
            assert len(owned) == 1, rows
            assert owned[0]["objid"] == key
            assert owned[0]["mode"] == "ShareLock" and owned[0]["granted"]
            current_locks = {identity(row) for row in rows}
            assert current_locks == baseline_locks | {identity(owned[0])}
            if original_locks is None:
                original_locks = current_locks
            assert current_locks == original_locks
            assert gate_locks._retained_shared_locks.get() == baseline_refs + (owner,)
            factory.assert_called_once_with()
            assert domain() == before
            assert tenant_and_transition_audits() == audits

    assert original_connection.closed
    assert not owner.acquired and owner.lock_connection is None
    assert gate_locks._retained_shared_locks.get() == baseline_refs
    assert {identity(row) for row in source_locks()} == baseline_locks
    factory.assert_called_once_with()
    assert domain() == before
    assert tenant_and_transition_audits() == audits
