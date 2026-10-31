"""Drive real dispatch checkpoints against a genuinely queued exclusive P writer."""
import json

from django.db import connection

from tests.claim_source_safety.observations import NProof, exclusive_n
from tests.box_parent_safety.pg_helpers import workers

from .dispatch_probe import observe_dispatch
from .p_observations import PProof, exclusive_p


def full_dispatch(settings, case, table, record_property, *, cleanup=False,
                  cleanup_makerspace_id=None):
    proof = PProof(record_property)
    nproof = NProof([cleanup_makerspace_id], record_property) if cleanup else None

    def cleanup_observation(execute, sql, params, many, context):
        if ('FROM "accounts_memberclaimcode"' in sql and "FOR UPDATE" in sql):
            nproof.observe("before_cleanup_claim_row_lock")
        if sql.startswith('UPDATE "presence_presencesession"'):
            nproof.observe("before_actual_cleanup_UPDATE")
            connection.on_commit(lambda: nproof.observe("actual_cleanup_commit"))
        return execute(sql, params, many, context)

    def operation(probe):
        if not cleanup:
            return probe.run(case.call)

        def call():
            with connection.execute_wrapper(cleanup_observation):
                return case.call()
        return probe.run(call)

    with workers() as start, observe_dispatch(settings, table) as probe:
        request = start(operation(probe))
        probe.enter.wait(request)
        proof.observe(request, "entry_before_auth", no_n=True)
        # Queue a real exclusive P before authentication. Every later checkpoint
        # must still show its exact blocking edge to the SAME retained P backend.
        exclusive = start(exclusive_p)
        proof.blocked_exclusive(exclusive)
        probe.enter.release.set()
        probe.update.wait(request)
        updates = [row for row in probe.completed_sql
                   if row["sql"].startswith(f'UPDATE "{table}"')]
        assert len(updates) == 1 and updates[0]["pid"] == request.pid
        assert updates[0]["completed"] is True
        if not cleanup:
            assert not any('"tenant_migration_sourcemigrationgate"' in row["sql"]
                           for row in probe.completed_sql)
        qr_tables = ('"makerspaces_makerspace"', '"boxes_box"', '"boxes_qrcode"',
                     '"inventory_inventoryproduct"', '"inventory_inventoryasset"')
        assert not any("FOR " in row["sql"] and any(table in row["sql"] for table in qr_tables)
                       for row in probe.completed_sql)
        proof.observe(request, "actual_auth_update", no_n=not cleanup)
        if cleanup:
            nproof.observe("actual_cleanup_UPDATE")
            exclusive_source = start(lambda: exclusive_n(cleanup_makerspace_id))
            nproof.queued(exclusive_source, cleanup_makerspace_id)
        proof.blocked_exclusive(exclusive)
        record_property("actual_auth_update", json.dumps(updates[0], default=str))
        probe.update.release.set()
        probe.audit.wait(request)
        assert any(row["sql"].startswith('INSERT INTO "audit_auditlog"')
                   and row["completed"] for row in probe.completed_sql)
        proof.observe(request, "actual_audit_insert", no_n=False)
        if cleanup:
            nproof.observe("actual_cleanup_audit_INSERT")
            nproof.queued(exclusive_source, cleanup_makerspace_id)
        proof.blocked_exclusive(exclusive)
        probe.audit.release.set()
        probe.tail.wait(request)
        proof.observe(request, "delegated_response_before_P_release", no_n=True)
        if cleanup:
            nproof.released()
            assert exclusive_source.finish() == "exclusive N acquired"
        proof.blocked_exclusive(exclusive)
        probe.tail.release.set()
        response = request.finish()
        assert exclusive.finish() == "exclusive P acquired"
        record_property("completed_SQL", json.dumps(probe.completed_sql, default=str))
    proof.released()
    return response, probe.completed_sql


def refused_dispatch(settings, case, record_property, *, before_auth=None):
    """The real policy can refuse before cleanup; never fabricate a successful path."""
    proof = PProof(record_property)
    with workers() as start, observe_dispatch(settings, "unused") as probe:
        request = start(probe.run(case.call))
        probe.enter.wait(request)
        proof.observe(request, "refused_entry", no_n=True)
        exclusive = start(exclusive_p)
        proof.blocked_exclusive(exclusive)
        if before_auth:
            before_auth()
        probe.enter.release.set()
        probe.tail.wait(request)
        assert not probe.update.reached.is_set() and not probe.audit.reached.is_set()
        proof.observe(request, "refused_tail", no_n=True)
        proof.blocked_exclusive(exclusive)
        probe.tail.release.set()
        response = request.finish()
        assert exclusive.finish() == "exclusive P acquired"
        record_property("refusal_completed_SQL", json.dumps(probe.completed_sql, default=str))
    proof.released()
    return response, probe.completed_sql
