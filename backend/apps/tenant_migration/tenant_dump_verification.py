"""Catalog, raw digest and identity checks shared by scratch and restored dump."""

from uuid import UUID

from django.apps import apps
from django.db import connections

from apps.backup.raw_projection import no_decrypt_guard
from apps.encryption.registry import fields_for

from .tenant_dump_catalog import validate_catalog, validate_unowned_tables
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_raw import (
    mapped_raw_digest,
    projected_raw_digest,
    validate_raw_column_allowlists,
)
from .tenant_dump_sql import (
    verify_foreign_key_closure,
    verify_open_tenant_fence,
    verify_source_disposition_tables_empty,
    verify_tables_empty,
)
from .tenant_dump_sequences import read_sequence_state
from .tenant_dump_cross_tenant_verify import verify_cross_tenant_projection
from .tenant_dump_user_closure import (
    reproduce_user_closure,
    verify_closure_digest,
)


def mapped_rows(using, identities):
    """Read only reviewed mapped columns and their PKs from a projected database."""
    result = {}
    connection = connections[using]
    quote = connection.ops.quote_name
    with no_decrypt_guard(), connection.cursor() as cursor:
        for label, pks in sorted(identities.items()):
            model = apps.get_model(label)
            mapped = fields_for(model)
            if not mapped or not pks:
                continue
            selected = [model._meta.pk.attname] + [item.field_name for item in mapped]
            fields = [model._meta.get_field(name) for name in selected]
            columns = ", ".join(quote(field.column) for field in fields)
            placeholders = ", ".join(["%s"] * len(pks))
            cursor.execute(
                f"SELECT {columns} FROM {quote(model._meta.db_table)} "
                f"WHERE {quote(model._meta.pk.column)} IN ({placeholders}) "
                f"ORDER BY {quote(model._meta.pk.column)}",
                list(pks),
            )
            result[label] = tuple(
                dict(zip((field.attname for field in fields), row, strict=True))
                for row in cursor.fetchall()
            )
    return result


def projected_rows(using, identities):
    """Read whole tables; an expected-empty table remains part of the universe."""
    from .tenant_dump_projection_rows import complete_projected_rows
    return complete_projected_rows(using, identities, {label: len(pks) for label, pks in identities.items()})


def verify_projection_database(
    using,
    makerspace_id,
    *,
    expected_row_counts,
    expected_cross_tenant_lost_edges,
    expected_semantic_references,
    source_expectations,
    bootstrap_baseline,
    bootstrap_generated,
    resolved_pks,
    expected_mapped_digest,
    mapped_identities,
    expected_projected_digest=None,
    projected_identities=None,
    expected_sequence_state=None,
    capture_id=None,
    expected_user_closure_digest=None,
):
    validate_catalog()
    validate_raw_column_allowlists()
    validate_unowned_tables(connections[using].introspection.table_names())
    verify_foreign_key_closure(using)
    verify_open_tenant_fence(using, makerspace_id)
    verify_tables_empty(using, {"spaceworks_cache"})
    verify_source_disposition_tables_empty(using)
    verify_cross_tenant_projection(using, makerspace_id)
    actual = mapped_raw_digest(mapped_rows(using, mapped_identities))
    if actual != expected_mapped_digest:
        raise TenantDumpVerificationError(
            "Mapped raw values differ between the immutable image and projection."
        )
    from .tenant_dump_projection_rows import complete_projected_rows, portable_content_rows, expected_target_identities
    from .tenant_dump_projection_bootstrap import verify_bootstrap_rows
    from .tenant_dump_projection_expectations import SourceProjectionExpectations
    from .tenant_dump_projection_loss import verify_loss_postconditions
    from .tenant_dump_semantic_expectations import verify_semantic_references

    if (not isinstance(source_expectations, SourceProjectionExpectations)
            or source_expectations.source_makerspace_id != makerspace_id
            or str(UUID(str(capture_id))) != source_expectations.capture_id
            or expected_user_closure_digest != source_expectations.user_closure_sha256
            or list(expected_semantic_references) != list(source_expectations.expected_semantic_references)
            or expected_projected_digest is None):
        raise TenantDumpVerificationError("Database verification requires its independent frozen source expectations.")
    frozen_identities = expected_target_identities(source_expectations, bootstrap_baseline)
    if projected_identities != frozen_identities or expected_row_counts != {
        label: len(pks) for label, pks in frozen_identities.items()
    }:
        raise TenantDumpVerificationError("The supplied identity/count expectations differ from frozen source facts.")
    rows = complete_projected_rows(using, frozen_identities, expected_row_counts)
    verify_bootstrap_rows(using, bootstrap_baseline, bootstrap_generated)
    verify_loss_postconditions(using, source_expectations.loss_facts, expected_cross_tenant_lost_edges)
    verify_semantic_references(rows, expected_semantic_references, resolved_pks=resolved_pks)
    if projected_raw_digest(portable_content_rows(rows)) != expected_projected_digest:
        raise TenantDumpVerificationError("A sanitized row differs from its frozen input projection.")
    if (
        expected_sequence_state is not None
        and read_sequence_state(using) != expected_sequence_state
    ):
        raise TenantDumpVerificationError(
            "Lane D sequence state changed across the custom dump."
        )
    if expected_user_closure_digest is not None:
        if capture_id is None:
            raise TenantDumpVerificationError(
                "Closure verification requires the artifact capture id."
            )
        verify_closure_digest(
            reproduce_user_closure(using, capture_id),
            expected_user_closure_digest,
        )
    return actual
