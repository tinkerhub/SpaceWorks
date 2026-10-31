"""Orchestrate the Phase D2 scratch projection and verified custom dump."""

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from uuid import UUID

from django.apps import apps
from django.db import connections, transaction

from apps.backup.raw_projection import no_decrypt_guard
from apps.backup.digests import sha256_file

from .tenant_dump_catalog import validate_catalog, validate_unowned_tables
from .tenant_dump_database import (
    dump_scratch_database,
    empty_verification_database,
    migrated_scratch_database,
    restore_scratch_dump,
)
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_graph import plan_row_load
from .tenant_dump_machine_types import resolve_machine_types
from .tenant_dump_pii import verify_ciphertext_aad_identities
from .tenant_dump_raw import (
    mapped_raw_digest,
    projected_raw_digest,
    validate_raw_column_allowlists,
)
from .tenant_dump_sql import (
    apply_deferred_foreign_keys,
    delete_portable_rows,
    empty_source_disposition_tables,
    insert_rows,
    verify_source_disposition_tables_empty,
    verify_tables_empty,
)
from .tenant_dump_sequences import normalize_sequences
from .tenant_dump_verification import verify_projection_database
from .tenant_dump_projection_load import (
    _portable_models, _sanitize_rows, _split_bootstrap_roots,
    _remap_member_roles, _mapped_identities, _final_rows, expected_projected_rows,
)

from .tenant_dump_projection_expectations import validate_source_expectations, verify_planned_identities
from .tenant_dump_projection_bootstrap import (
    capture_bootstrap_baseline, seed_projection_roles, close_projection_fence,
    open_projection_fence, bootstrap_sha256,
)
from .tenant_dump_projection_rows import expected_target_identities
from .tenant_dump_projection_proof import build_projection_record, canonical_digest


@dataclass(frozen=True)
class TenantDumpBuildResult:
    database_dump: Path
    mapped_raw_sha256: str
    sequence_state: dict
    used_two_pass: bool
    projection_verification: dict


def build_tenant_dump(
    projection, destination, *, run_id, source_pii_mode, expectations, database=None
):
    """Build one target-compatible dump exclusively from a frozen D1 projection."""
    validate_source_expectations(projection, expectations, run_id)
    makerspace_id = int(projection.makerspace_id)
    operation_id = UUID(str(run_id))
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    validate_catalog()
    validate_raw_column_allowlists()
    if projection.user_closure is None:
        raise TenantDumpVerificationError(
            "The Lane D projection lacks its immutable-image user closure."
        )
    expected_digest = mapped_raw_digest(projection.rows)
    mapped_identities = _mapped_identities(projection.rows)
    models = _portable_models()
    used_two_pass = False

    with tempfile.TemporaryDirectory(
        prefix=".spaceworks-tenant-dump-", dir=destination.parent
    ) as temporary:
        candidate = Path(temporary, "database.dump")
        with migrated_scratch_database(
            makerspace_id, run_id, database=database
        ) as (using, database_name):
            validate_unowned_tables(connections[using].introspection.table_names())
            with transaction.atomic(using=using), no_decrypt_guard():
                with connections[using].cursor() as cursor:
                    cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
                delete_portable_rows(using, makerspace_id, models)
                verify_tables_empty(using, {"spaceworks_cache"})
                baseline = capture_bootstrap_baseline(using)
                source_rows = {
                    label: tuple(rows) for label, rows in projection.rows.items()
                }
                machine_type_model = apps.get_model("machines.MachineType")
                resolved_pks, custom_types = resolve_machine_types(
                    using,
                    source_rows.get("machines.MachineType", ()),
                    machine_type_model,
                )
                source_rows["machines.MachineType"] = custom_types
                sanitized = _sanitize_rows(source_rows, makerspace_id)
                verify_planned_identities(sanitized, expectations)
                roots, remainder = _split_bootstrap_roots(sanitized)
                root_plan = plan_row_load(roots, resolved_pks=resolved_pks)
                if root_plan.used_two_pass:
                    raise TenantDumpVerificationError(
                        "User/makerspace bootstrap unexpectedly requires a nullable cycle."
                    )
                verify_planned_identities((*root_plan.rows, *remainder), expectations)
                insert_rows(using, root_plan.rows)
                fence = close_projection_fence(using, makerspace_id, operation_id)
                role_ids, generated = seed_projection_roles(using, makerspace_id, baseline)
                remainder = _remap_member_roles(remainder, role_ids["member"])
                expected_rows = expected_projected_rows((*roots, *remainder), resolved_pks)
                projected_digest = projected_raw_digest(expected_rows)
                plan = plan_row_load(remainder, resolved_pks=resolved_pks)
                verify_planned_identities((*root_plan.rows, *plan.rows), expectations)
                insert_rows(using, plan.rows)
                apply_deferred_foreign_keys(
                    using,
                    plan.deferred_foreign_keys,
                    {row.identity: row for row in plan.rows},
                )
                used_two_pass = plan.used_two_pass
                empty_source_disposition_tables(using)
                generated["encryption.PiiMakerspaceWriteFence"] = open_projection_fence(using, fence)
                sequence_state = normalize_sequences(using)
                final_rows = _final_rows(
                    (*root_plan.rows, *plan.rows), plan.deferred_foreign_keys
                )
                verify_ciphertext_aad_identities(
                    projection.rows,
                    final_rows,
                    makerspace_id,
                    mode=source_pii_mode,
                )
                if projected_raw_digest(final_rows) != projected_digest:
                    raise TenantDumpVerificationError("The planned row content changed its frozen input projection.")
                projected_identities = expected_target_identities(expectations, baseline)
                row_counts = {label: len(pks) for label, pks in projected_identities.items()}
                verification = dict(
                    expected_mapped_digest=expected_digest, mapped_identities=mapped_identities,
                    expected_projected_digest=projected_digest, projected_identities=projected_identities,
                    expected_row_counts=row_counts,
                    expected_cross_tenant_lost_edges=expectations.expected_cross_tenant_lost_edges,
                    expected_semantic_references=expectations.expected_semantic_references,
                    source_expectations=expectations, bootstrap_baseline=baseline,
                    bootstrap_generated=generated, resolved_pks=resolved_pks,
                    expected_sequence_state=sequence_state, capture_id=run_id,
                    expected_user_closure_digest=expectations.user_closure_sha256,
                )
            verify_projection_database(using, makerspace_id, **verification)
            scratch_projected_sha256 = projected_digest
            # Keep this adjacent to pg_dump: future verification code cannot make
            # runtime cache state accidentally portable.
            verify_tables_empty(using, {"spaceworks_cache"})
            verify_source_disposition_tables_empty(using)
            dump_scratch_database(database_name, candidate, database=database)
            if not candidate.is_file() or candidate.stat().st_size <= 0:
                raise TenantDumpVerificationError("The Lane D database dump is empty.")
            candidate_sha256 = sha256_file(candidate)

        with empty_verification_database(
            makerspace_id, run_id, database=database
        ) as (using, database_name):
            restore_scratch_dump(candidate, database_name, database=database)
            restored_digest = verify_projection_database(using, makerspace_id, **verification)
            restored_projected_sha256 = projected_digest
            if restored_digest != expected_digest:
                raise TenantDumpVerificationError(
                    "The custom dump changed a mapped raw value."
                )
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            raise TenantDumpVerificationError("The verified Lane D database dump is empty.")
        if sha256_file(candidate) != candidate_sha256:
            raise TenantDumpVerificationError("The candidate dump bytes changed across verification.")
        proof = build_projection_record(
            expectations, database_member_sha256=candidate_sha256, row_counts=row_counts,
            row_identity_sha256=canonical_digest({
                label: [str(pk) for pk in pks] for label, pks in projected_identities.items()
            }),
            bootstrap_sha256=bootstrap_sha256(baseline, generated),
            mapped_raw_sha256=expected_digest, projected_raw_sha256=projected_digest,
            scratch_projected_sha256=scratch_projected_sha256,
            restored_projected_sha256=restored_projected_sha256,
        )
        candidate.chmod(0o600)
        os.replace(candidate, destination)
    return TenantDumpBuildResult(
        database_dump=destination,
        mapped_raw_sha256=expected_digest,
        sequence_state=sequence_state,
        used_two_pass=used_two_pass,
        projection_verification=proof,
    )
