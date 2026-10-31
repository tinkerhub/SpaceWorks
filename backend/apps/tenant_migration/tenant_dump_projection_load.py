"""Focused row planning helpers for the Lane D builder."""

from django.apps import apps
from apps.data_export.datasets import DATASET_SPECS
from .tenant_dump_cross_tenant import project_cross_tenant_values
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from .tenant_dump_raw import SanitizedRow, sanitize_record
from .tenant_dump_types import ModelDisposition


def _portable_models():
    return tuple(
        apps.get_model(label)
        for label in DATASET_SPECS
        if FIRST_PARTY_MODEL_RULES[label].disposition
        in {ModelDisposition.PROJECT, ModelDisposition.PRESERVE_LIVE}
    )


def _sanitize_rows(rows_by_label, makerspace_id):
    result = []
    for label, rows in sorted(rows_by_label.items()):
        rule = FIRST_PARTY_MODEL_RULES[label]
        if rule.disposition not in {
            ModelDisposition.PROJECT,
            ModelDisposition.PRESERVE_LIVE,
        }:
            continue
        model = apps.get_model(label)
        result.extend(
            _apply_contextual_dispositions(
                sanitize_record(model, row), row, makerspace_id
            )
            for row in rows
        )
    return result


def _apply_contextual_dispositions(row, source, makerspace_id):
    """Apply row-context rules whose result cannot be a table-wide field label."""
    values = dict(row.values)
    label = row.model._meta.label
    values = project_cross_tenant_values(
        row.model, values, source, makerspace_id
    )
    if label == "events.EventRegistration":
        # Search generations and their blind-index rows are target-derived and empty
        # in the scratch bootstrap; ciphertext itself remains byte-identical.
        values[row.model._meta.get_field("email_exact_hash").column] = None
        values[row.model._meta.get_field("email_hash_generation").column] = None
    return SanitizedRow(row.model, row.source_pk, values)


def _split_bootstrap_roots(rows):
    root_labels = {"accounts.User", "makerspaces.Makerspace"}
    return (
        [row for row in rows if row.model._meta.label in root_labels],
        [row for row in rows if row.model._meta.label not in root_labels],
    )


def _remap_member_roles(rows, member_role_id):
    result = []
    labels = {"makerspaces.MakerspaceMembership", "makerspaces.MembershipRequest"}
    for row in rows:
        if row.model._meta.label not in labels:
            result.append(row)
            continue
        field = row.model._meta.get_field("assigned_role")
        values = dict(row.values)
        values[field.column] = member_role_id
        result.append(SanitizedRow(row.model, row.source_pk, values))
    return result


def _mapped_identities(rows_by_label):
    result = {}
    for label, rows in rows_by_label.items():
        model = apps.get_model(label)
        from apps.encryption.registry import fields_for

        if fields_for(model):
            result[label] = tuple(row[model._meta.pk.attname] for row in rows)
    return result


def _final_rows(rows, deferred):
    by_identity = {row.identity: row for row in rows}
    final_values = {identity: dict(row.values) for identity, row in by_identity.items()}
    for update in deferred:
        final_values[update.identity][update.column] = update.value
    result = {}
    for identity, row in by_identity.items():
        record = {
            field.attname: final_values[identity][field.column]
            for field in row.model._meta.concrete_fields
        }
        result.setdefault(row.model._meta.label, []).append(record)
    return {label: tuple(values) for label, values in result.items()}


def expected_projected_rows(rows, resolved_pks):
    """Freeze content before planning, independently of plan outputs/deferred edges."""
    result = {}
    for row in rows:
        record = {}
        for field in row.model._meta.concrete_fields:
            value = row.values[field.column]
            if field.is_relation and field.related_model is not None:
                value = resolved_pks.get((field.related_model._meta.label, value), value)
            record[field.attname] = value
        result.setdefault(row.model._meta.label, []).append(record)
    return {label: tuple(records) for label, records in result.items()}
