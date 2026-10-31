"""One real PG custom-dump roundtrip probes both independent verifier boundaries."""

from dataclasses import replace

import pytest
from django.apps import apps
from django.db import connections, transaction

from apps.backup.digests import sha256_file
from apps.tenant_migration import tenant_dump_builder as builder
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_dump_projection_expectations import verify_planned_identities
from apps.tenant_migration.tenant_dump_projection_load import _sanitize_rows, expected_projected_rows
from apps.tenant_migration.tenant_dump_projection_proof import (
    canonical_digest, validate_projection_record, validate_projection_verification,
)
from apps.tenant_migration.tenant_dump_pii import PLAINTEXT
from apps.tenant_migration.tenant_dump_raw import projected_raw_digest
from apps.tenant_migration.tenant_dump_sequences import normalize_sequences
from .x13_boundary_mutations import ROW_CASES, corrupt_loss, recompute_old_digest
from .x13_proof_helpers import inner_for_proof, outer_for_inner
from .x13_source_helpers import (
    OWNER, FULL, STUB, CUSTOM, MACHINE, BUILTIN_MACHINE, PRODUCT, TRANSFER,
    FOREIGN_TRANSFER, MEMBERSHIP, AUDIT, SNAPSHOT, freeze_source,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("allow_projection_databases")]


def assert_valid_target(using, old_builtin_pk):
    def manager(label):
        return apps.get_model(label)._base_manager.using(using)

    types = manager("machines.MachineType")
    assert types.filter(makerspace_id=None).count() > 1  # unused target builtins survive
    assert types.get(pk=CUSTOM).name == "Custom type"
    assert manager("machines.Machine").get(pk=MACHINE).machine_type_id == CUSTOM
    assert manager("machines.Machine").get(pk=BUILTIN_MACHINE).machine_type_id == old_builtin_pk
    assert manager("accounts.User").get(pk=FULL).email == "ordinary-user@example.test"
    stub = manager("accounts.User").get(pk=STUB)
    assert stub.is_tenant_dump_stub and not stub.is_active and stub.email == ""
    assert manager("makerspaces.MakerspaceMembership").get(pk=MEMBERSHIP).activated_actor_snapshot == SNAPSHOT
    assert manager("accounts.User").get(pk=int(SNAPSHOT["source_user_id"])).username == "unrelated-reused-pk"
    audit = manager("audit.AuditLog").get(pk=AUDIT)
    assert audit.target_id == str(old_builtin_pk)
    assert audit.meta["actor"] == SNAPSHOT
    assert types.get(pk=old_builtin_pk).name != "Deleted historical type"
    assert audit.event_uuid is None and audit.row_mac is None
    assert manager("inventory.InventoryProduct").get(pk=PRODUCT).name == "Ordinary stock"
    transfer = manager("operations.StockTransfer").get(pk=TRANSFER)
    assert transfer.source_makerspace_id == OWNER and transfer.source_container_id is not None
    assert transfer.destination_makerspace_id is None and transfer.destination_container_id is None
    assert not manager("operations.StockTransfer").filter(pk=FOREIGN_TRANSFER).exists()
    assert not manager("operations.StockTransferLine").filter(transfer_id=FOREIGN_TRANSFER).exists()
    assert not manager("events.EventCollaborator").exists()
    assert not manager("events.EventSeriesCollaborator").exists()
    registration = manager("events.EventRegistration").get()
    assert registration.registered_via_makerspace_id is None and registration.payment_via_makerspace_id is None
    payment = manager("payments.Payment").get()
    assert str(payment.amount) == "42.75" and payment.subject_label == "Readable history"
    assert payment.external_order_id is None and payment.via_makerspace_id is None
    roles = manager("makerspaces.MakerspaceRole")
    assert roles.count() == 4 and roles.filter(is_protected=True).count() == 4
    assert manager("machines.RoleMachineTypeScope").count() == types.filter(makerspace_id=None).count()
    assert manager("auth.Permission").exists() and manager("contenttypes.ContentType").exists()


def assert_preload_identity_refusal(projection, expectations):
    source = dict(projection.rows)
    source["machines.MachineType"] = tuple(
        row for row in source["machines.MachineType"] if row["makerspace_id"] is not None
    )
    planned = _sanitize_rows(source, OWNER)
    verify_planned_identities(planned, expectations)
    selected = next(row for row in planned if row.model._meta.label == "inventory.Category")
    extra = replace(selected, source_pk=799999, values=dict(selected.values, id=799999))
    for bad in ([row for row in planned if row is not selected], [*planned, extra]):
        # The historical full-row digest can be recomputed by a bad load plan;
        # it is not an independent identity expectation.
        assert len(projected_raw_digest(expected_projected_rows(bad, {}))) == 64
        with pytest.raises(TenantDumpVerificationError, match="load plan.*frozen"):
            verify_planned_identities(bad, expectations)


def test_real_builder_custom_dump_roundtrip_reconciles_both_boundaries(tmp_path, monkeypatch):
    database = dict(connections["default"].settings_dict)
    projection, expectations, old_builtin_pk = freeze_source(database, tmp_path)
    assert_preload_identity_refusal(projection, expectations)
    original = builder.verify_projection_database
    visits, refusals = [], []

    def probe(using, makerspace_id, **kwargs):
        boundary = "restored" if using.startswith("tenant_dump_verify_") else "scratch"
        visits.append(boundary)
        # Both baseline calls and all negative probes execute the production
        # verifier; no mocked success or verified boolean substitutes for it.
        actual = original(using, makerspace_id, **kwargs)
        assert_valid_target(using, old_builtin_pk)
        for name, mutate, message, recompute in ROW_CASES:
            with transaction.atomic(using=using):
                with connections[using].cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                mutate(using)
                changed = dict(kwargs)
                if name != "sequence_frontier":
                    changed["expected_sequence_state"] = normalize_sequences(using)
                if recompute:
                    recompute_old_digest(using, changed)
                with pytest.raises(TenantDumpVerificationError, match=message):
                    original(using, makerspace_id, **changed)
                refusals.append((boundary, name))
                transaction.set_rollback(True, using=using)
            # setval is not transactional; restore frontiers after row rollback.
            assert normalize_sequences(using) == kwargs["expected_sequence_state"]
        for mode in ("omit", "add", "change"):
            changed = dict(kwargs, expected_cross_tenant_lost_edges=corrupt_loss(
                kwargs["expected_cross_tenant_lost_edges"], mode))
            with pytest.raises(TenantDumpVerificationError, match="loss ledger.*frozen"):
                original(using, makerspace_id, **changed)
            refusals.append((boundary, "loss_" + mode))
        for parameter, value, message in (
            ("expected_row_counts", dict(kwargs["expected_row_counts"], **{"inventory.Category": 999}), "identity/count"),
            ("expected_semantic_references", (), "independent frozen"),
        ):
            with pytest.raises(TenantDumpVerificationError, match=message):
                original(using, makerspace_id, **dict(kwargs, **{parameter: value}))
            refusals.append((boundary, parameter))
        assert original(using, makerspace_id, **kwargs) == actual
        return actual

    monkeypatch.setattr(builder, "verify_projection_database", probe)
    result = builder.build_tenant_dump(
        projection, tmp_path / "database.dump", run_id=expectations.capture_id,
        source_pii_mode=PLAINTEXT, expectations=expectations, database=database,
    )
    assert isinstance(result, builder.TenantDumpBuildResult)
    assert visits == ["scratch", "restored"]
    expected_cases = {case[0] for case in ROW_CASES} | {
        "loss_omit", "loss_add", "loss_change", "expected_row_counts", "expected_semantic_references",
    }
    assert set(refusals) == {(boundary, case) for boundary in visits for case in expected_cases}
    assert result.database_dump.read_bytes()[:5] == b"PGDMP"
    proof = result.projection_verification
    assert proof["database_member_sha256"] == sha256_file(result.database_dump)
    assert proof["source_database_image_sha256"] == sha256_file(tmp_path / "database.source.dump")
    assert proof["row_counts"]["inventory.InventoryAsset"] == 0
    assert proof["scratch_projected_sha256"] == proof["restored_projected_sha256"] == proof["projected_raw_sha256"]
    inner = inner_for_proof(proof, projection.user_closure.manifest(), size=result.database_dump.stat().st_size)
    inner["cross_tenant_lost_edges"] = [dict(item) for item in projection.cross_tenant_lost_edges]
    facts = validate_projection_record(inner)
    assert facts.proof_sha256 == proof["sha256"]
    assert facts.database_member_sha256 == inner["contents"][0]["sha256"] == sha256_file(result.database_dump)
    assert validate_projection_verification(inner, outer_manifest=outer_for_inner(inner)) == facts
    assert proof["cross_tenant_lost_edges_sha256"] == canonical_digest(inner["cross_tenant_lost_edges"])
