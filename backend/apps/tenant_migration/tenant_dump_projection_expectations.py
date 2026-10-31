"""Immutable source expectations captured before the source alias is closed."""

from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID
from django.apps import apps

from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from .tenant_dump_types import ModelDisposition
from .tenant_dump_raw import projected_raw_digest
from .tenant_dump_projection_loss import capture_loss_facts, derive_loss_decisions
from .tenant_dump_semantic_expectations import extract_semantic_references


def projected_labels():
    from .tenant_dump_projection_schema import PROJECTED_LABELS
    labels = {label for label, rule in FIRST_PARTY_MODEL_RULES.items()
              if rule.disposition in {ModelDisposition.PROJECT, ModelDisposition.PRESERVE_LIVE}}
    if labels != PROJECTED_LABELS:
        raise TenantDumpVerificationError("The proof schema's reviewed projected labels drifted.")
    return tuple(sorted(labels))


@dataclass(frozen=True)
class SourceProjectionExpectations:
    capture_id: str
    source_makerspace_id: int
    source_database_image_sha256: str
    catalog_sha256: str
    derivation_policy_sha256: str
    source_rows_sha256: str
    allowed_identities: object
    expected_row_counts: object
    builtin_source_ids: frozenset
    loss_facts: object
    expected_cross_tenant_lost_edges: tuple
    expected_semantic_references: tuple
    user_closure_sha256: str


def capture_projection_expectations(projection, *, capture_id,
                                    source_database_image_sha256, catalog_sha256,
                                    derivation_policy_sha256, using):
    """No target query or supplied loss ledger is used as its own expectation."""
    capture = str(UUID(str(capture_id)))
    owner = projection.makerspace_id
    if type(owner) is not int or owner <= 0 or projection.user_closure is None:
        raise TenantDumpVerificationError("Source expectations require an owner and frozen user closure.")
    for value in (source_database_image_sha256, catalog_sha256, derivation_policy_sha256):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise TenantDumpVerificationError("Source expectation bindings require canonical SHA256 values.")
    identities = {}
    for label in projected_labels():
        model = apps.get_model(label)
        pks = tuple(sorted((row[model._meta.pk.attname] for row in projection.rows.get(label, ())), key=str))
        if len(set(pks)) != len(pks):
            raise TenantDumpVerificationError("Source expectations contain duplicate row identities.")
        identities[label] = pks
    facts = capture_loss_facts(owner, using=using)
    losses = derive_loss_decisions(facts).manifest()
    if losses != [dict(item) for item in projection.cross_tenant_lost_edges]:
        raise TenantDumpVerificationError("The projection loss ledger differs from immutable source ownership.")
    return SourceProjectionExpectations(
        capture, owner, source_database_image_sha256, catalog_sha256,
        derivation_policy_sha256, _source_rows_digest(projection.rows),
        MappingProxyType(identities), MappingProxyType({label: len(pks) for label, pks in identities.items()}),
        frozenset(row["id"] for row in projection.rows.get("machines.MachineType", ())
                  if row["makerspace_id"] is None), facts,
        tuple(MappingProxyType(item) for item in losses),
        tuple(MappingProxyType(item) for item in extract_semantic_references(projection.rows, expected=True)),
        projection.user_closure.digest,
    )


def validate_source_expectations(projection, expectations, capture_id):
    if not isinstance(expectations, SourceProjectionExpectations):
        raise TenantDumpVerificationError("A strong Lane D build requires frozen source expectations.")
    if (expectations.capture_id != str(UUID(str(capture_id)))
            or expectations.source_makerspace_id != projection.makerspace_id
            or expectations.source_rows_sha256 != _source_rows_digest(projection.rows)
            or projection.user_closure is None
            or expectations.user_closure_sha256 != projection.user_closure.digest
            or list(expectations.expected_cross_tenant_lost_edges) != list(projection.cross_tenant_lost_edges)):
        raise TenantDumpVerificationError("The frozen source projection or bindings changed before build.")


def verify_planned_identities(rows, expectations):
    actual = {label: [] for label in projected_labels()}
    for row in rows:
        actual[row.model._meta.label].append(row.source_pk)
    expected = {label: tuple(pks) for label, pks in expectations.allowed_identities.items()}
    expected["machines.MachineType"] = tuple(pk for pk in expected["machines.MachineType"]
                                             if pk not in expectations.builtin_source_ids)
    if {label: tuple(sorted(pks, key=str)) for label, pks in actual.items()} != expected:
        raise TenantDumpVerificationError("The load plan differs from the frozen allowed source identities.")


def _source_rows_digest(rows):
    return projected_raw_digest({label: tuple(dict(row) for row in records)
                                 for label, records in rows.items()})
