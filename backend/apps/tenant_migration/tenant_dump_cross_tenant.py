"""Exact D6 cross-tenant and payment row/field dispositions."""

from dataclasses import dataclass

from django.apps import apps

from apps.data_export.fields import EXTERNAL_REFERENCES

from .tenant_dump_errors import (
    TenantDumpDispositionRefused,
)
from .tenant_dump_cross_tenant_rules import (
    CROSS_TENANT_EDGE_RULES,
    PAYMENT_CLEARED_VALUES,
    CrossTenantDisposition,
)


@dataclass(frozen=True)
class CrossTenantSourceFacts:
    lost_edges: tuple[dict, ...]
    dropped_transfer_line_ids: frozenset[int]
    nulled_transfer_pairs: frozenset[tuple[int, str]]


def inspect_cross_tenant_source(makerspace_id, *, using="default"):
    """Read cross-tenant facts only from the immutable source database image."""
    validate_cross_tenant_registry()
    makerspace_id = int(makerspace_id)
    from .tenant_dump_projection_loss import capture_loss_facts, derive_loss_decisions

    facts = capture_loss_facts(makerspace_id, using=using)
    decisions = derive_loss_decisions(facts)
    nulled_pairs = set()
    by_pk = {dict(fields)["id"]: dict(fields) for label, fields in facts.ownership_rows
             if label == "operations.StockTransfer"}
    for pk, prefix, space, container in decisions.transfer_pairs:
        source = by_pk[pk]
        if (space, container) != (source[f"{prefix}_makerspace_id"], source[f"{prefix}_container_id"]):
            nulled_pairs.add((pk, prefix))
    return CrossTenantSourceFacts(
        tuple(decisions.manifest()),
        frozenset(pk for label, pk in decisions.dropped if label == "operations.StockTransferLine"),
        frozenset(nulled_pairs),
    )


def validate_cross_tenant_registry(rules=CROSS_TENANT_EDGE_RULES):
    if set(rules) != set(EXTERNAL_REFERENCES):
        raise TenantDumpDispositionRefused(
            "The cross-tenant FK registry has an unclassified edge.",
            reason_code="unclassified_cross_tenant_edge",
        )
    for (label, field_name), rule in rules.items():
        field = apps.get_model(label)._meta.get_field(field_name)
        if not field.concrete or not field.is_relation or not rule.reason:
            raise TenantDumpDispositionRefused(
                f"Cross-tenant rule {label}.{field_name} is invalid.",
                reason_code="invalid_cross_tenant_edge",
            )
        if rule.disposition is not CrossTenantDisposition.DROP_ROW and not field.null:
            raise TenantDumpDispositionRefused(
                f"Cross-tenant rule {label}.{field_name} cannot legally null.",
                reason_code="non_nullable_cross_tenant_edge",
            )
    return True


def project_cross_tenant_values(model, values, source, makerspace_id):
    """Apply the paired StockTransfer null rule to one already-sanitized row."""
    if model._meta.label != "operations.StockTransfer":
        return values
    projected = dict(values)
    for makerspace_field, container_field in (
        ("source_makerspace", "source_container"),
        ("destination_makerspace", "destination_container"),
    ):
        field = model._meta.get_field(makerspace_field)
        prefix = makerspace_field.removesuffix("_makerspace")
        if source.get(f"_d6_null_{prefix}_pair") or source.get(
            field.attname
        ) not in (None, int(makerspace_id)):
            projected[field.column] = None
            projected[model._meta.get_field(container_field).column] = None
    return projected


def _loss(model_label, source_row_pk, field_name, reason_code):
    return {
        "model_label": model_label,
        "source_row_pk": source_row_pk,
        "field_name": field_name,
        "reason_code": reason_code,
    }


def _loss_key(item):
    fields = ("model_label", "source_row_pk", "field_name", "reason_code")
    return tuple(str(item[name]) for name in fields)
