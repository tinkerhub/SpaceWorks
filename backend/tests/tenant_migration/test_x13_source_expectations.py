"""Independent policy facts, not target rows or a supplied loss manifest."""

from dataclasses import replace
from types import MappingProxyType

import pytest

from apps.data_export.types import Fidelity, SemanticUserRef
from apps.tenant_migration import tenant_dump_projection_loss as loss
from apps.tenant_migration import tenant_dump_semantic_expectations as semantic
from apps.tenant_migration.tenant_dump_cross_tenant_rules import (
    CROSS_TENANT_EDGE_RULES, CrossTenantDisposition, CrossTenantRule,
)
from apps.tenant_migration.tenant_dump_errors import (
    TenantDumpDispositionRefused, TenantDumpVerificationError,
)
from apps.tenant_migration.tenant_dump_projection_expectations import validate_source_expectations
from apps.tenant_migration.tenant_dump_source_projection import TenantDumpSourceProjection
from apps.tenant_migration.tenant_dump_projection_expectations import SourceProjectionExpectations
from apps.tenant_migration.tenant_dump_raw import projected_raw_digest
from apps.tenant_migration.tenant_dump_catalog import CATALOG_SCHEMA_SHA256
from apps.tenant_migration.tenant_dump_projection_proof import canonical_digest, FORMAT


def facts(owner, *rows):
    return loss.SourceLossFacts(owner, tuple((label, tuple(sorted(row.items()))) for label, row in rows))


@pytest.mark.parametrize("series", [False, True], ids=["occurrence", "series"])
@pytest.mark.parametrize("host,invited,field", [(1, 2, "makerspace"), (2, 1, "parent")],
                         ids=["foreign-invited", "foreign-host"])
def test_source_oracle_names_both_foreign_collaborator_orientations(series, host, invited, field):
    label = "events.EventSeriesCollaborator" if series else "events.EventCollaborator"
    parent = "series" if series else "event"
    frozen = facts(1, (label, dict(id=17, makerspace_id=invited, **{parent + "__makerspace_id": host})))
    decisions = loss.derive_loss_decisions(frozen)
    assert decisions.manifest() == [dict(
        model_label=label, source_row_pk=17, field_name=parent if field == "parent" else field,
        reason_code="foreign_series_collaborator_dropped" if series else "foreign_collaborator_dropped",
    )]
    assert decisions.dropped == {(label, 17)}
    assert decisions.transfer_pairs == ()


def test_local_collaborator_authority_drops_without_inventing_a_foreign_loss():
    frozen = facts(1, ("events.EventCollaborator", dict(id=1, makerspace_id=1, event__makerspace_id=1)),
                   ("events.EventSeriesCollaborator", dict(id=2, makerspace_id=1, series__makerspace_id=1)))
    decisions = loss.derive_loss_decisions(frozen)
    assert decisions.manifest() == []
    assert decisions.dropped == {("events.EventCollaborator", 1), ("events.EventSeriesCollaborator", 2)}


def test_source_oracle_preserves_local_pairs_and_clears_both_foreign_pair_values():
    frozen = facts(1, ("operations.StockTransfer", dict(
        id=7, makerspace_id=1, source_makerspace_id=1, source_container_id=11,
        source_container__makerspace_id=1, destination_makerspace_id=2,
        destination_container_id=12, destination_container__makerspace_id=2,
    )), ("operations.StockTransfer", dict(
        id=8, makerspace_id=2, source_makerspace_id=2, source_container_id=12,
        source_container__makerspace_id=2, destination_makerspace_id=1,
        destination_container_id=11, destination_container__makerspace_id=1,
    )), ("operations.StockTransferLine", dict(
        id=9, transfer_id=8, transfer__makerspace_id=2, product__makerspace_id=2, asset__makerspace_id=None,
    )))
    decisions = loss.derive_loss_decisions(frozen)
    assert decisions.transfer_pairs == ((7, "destination", None, None), (7, "source", 1, 11))
    assert decisions.dropped == {("operations.StockTransfer", 8), ("operations.StockTransferLine", 9)}
    assert {(row["model_label"], row["source_row_pk"], row["field_name"], row["reason_code"])
            for row in decisions.manifest()} == {
        ("operations.StockTransfer", 7, "destination_makerspace", "foreign_counterparty_nulled"),
        ("operations.StockTransfer", 7, "destination_container", "foreign_counterparty_container_nulled"),
        ("operations.StockTransfer", 8, "makerspace", "foreign_owned_transfer_dropped"),
        ("operations.StockTransferLine", 9, "transfer", "foreign_owned_transfer_line_dropped"),
    }


def test_proof_handler_registry_is_exact_including_derived_transfer_lines():
    loss.validate_loss_handlers()
    assert set(loss.EDGE_HANDLERS) == set(CROSS_TENANT_EDGE_RULES) | {("operations.StockTransferLine", "transfer")}
    assert loss.EDGE_HANDLERS[("events.EventRegistration", "registered_via_makerspace")] == "registration_reset"
    assert loss.EDGE_HANDLERS[("payments.Payment", "via_makerspace")] == "terminal_payment_reset"


@pytest.mark.parametrize("change", ["missing_handler", "unknown_edge", "changed_disposition"])
def test_unknown_or_changed_source_edge_cannot_silently_skip_the_oracle(monkeypatch, change):
    if change == "missing_handler":
        handlers = dict(loss.EDGE_HANDLERS)
        handlers.pop(("events.EventSeriesCollaborator", "series"))
        monkeypatch.setattr(loss, "EDGE_HANDLERS", handlers)
    else:
        registry = dict(loss.CROSS_TENANT_EDGE_RULES)
        key = ("events.Event", "makerspace") if change == "unknown_edge" else ("payments.Payment", "via_makerspace")
        registry[key] = CrossTenantRule(CrossTenantDisposition.NULL, "test schema drift")
        monkeypatch.setattr(loss, "CROSS_TENANT_EDGE_RULES", registry)
    with pytest.raises(TenantDumpDispositionRefused) as refused:
        loss.derive_loss_decisions(facts(1))
    assert refused.value.reason_code == "unclassified_cross_tenant_proof_handler"


def test_unknown_included_semantic_user_handler_refuses_even_an_empty_projection(monkeypatch):
    key = (Fidelity.PORTABLE, "audit.AuditLog", "json:meta")
    monkeypatch.setitem(semantic.SEMANTIC_REFERENCES, key, (
        SemanticUserRef("audit.AuditLog", "json:meta", "new live reference without handler"),
    ))
    with pytest.raises(TenantDumpVerificationError, match="included semantic user reference"):
        semantic.extract_semantic_references({}, expected=True)


def test_raw_service_owner_and_fence_actor_edge_classifications_are_consumed(monkeypatch):
    key = (Fidelity.PORTABLE, "machines.ServiceRequestFile", "owner_user_id")
    edge = semantic.USER_EDGES[key]
    monkeypatch.setitem(semantic.USER_EDGES, key, replace(edge, included=False))
    with pytest.raises(TenantDumpVerificationError, match="service-file owner"):
        semantic.semantic_locations()


def test_target_fence_actor_cannot_be_reclassified_as_imported_live_user_authority(monkeypatch):
    key = (Fidelity.PORTABLE, "encryption.PiiMakerspaceWriteFence", "actor_id")
    monkeypatch.setitem(semantic.USER_EDGES, key, replace(semantic.USER_EDGES[key], included=True))
    with pytest.raises(TenantDumpVerificationError, match="Target fence actors"):
        semantic.semantic_locations()


def test_semantics_preserve_deleted_audit_targets_actor_snapshots_and_user_json_literals():
    # A relation-free record fixture deliberately supplies no live target rows.
    rows = {"audit.AuditLog": ({"id": 8, "target_type": "accounts.user", "target_id": "17",
                               "meta": {"actor": {"source_user_id": "17", "actor_username": "deleted"},
                                        "arbitrary_user_content": {"user_id": 999}}},)}
    expected = semantic.extract_semantic_references(rows, expected=True)
    assert len(expected) == 2
    semantic.verify_semantic_references(rows, expected, resolved_pks={("accounts.User", 17): 999})
    altered = {"audit.AuditLog": (dict(rows["audit.AuditLog"][0], target_id="999"),)}
    with pytest.raises(TenantDumpVerificationError, match="Semantic location"):
        semantic.verify_semantic_references(altered, expected, resolved_pks={("accounts.User", 17): 999})


@pytest.mark.parametrize("binding", ["capture_id", "source_makerspace_id", "source_rows_sha256", "user_closure_sha256"])
def test_frozen_source_binding_drift_refuses_before_target_loading(binding):
    # No fabricated model fields: an empty record universe is enough to exercise
    # the source binding contract; the real builder test covers the complete graph.
    capture = "568267be-8127-4da6-810d-d3c2b90c6fc0"
    from apps.tenant_migration.tenant_dump_user_closure import UserClosure
    closure = UserClosure((), (), (), canonical_digest(dict(included=[], stubbed=[], refused=[])))
    projection = TenantDumpSourceProjection(1, MappingProxyType({}), (), user_closure=closure)
    expected = SourceProjectionExpectations(
        capture, 1, canonical_digest("fixture source image"), CATALOG_SCHEMA_SHA256,
        canonical_digest(dict(format=FORMAT, policy_version=6, catalog_digest=CATALOG_SCHEMA_SHA256,
                              source_encryption_mode=False, companion_slice=False)), projected_raw_digest({}),
        {}, {}, frozenset(), facts(1), (), (), closure.digest,
    )
    validate_source_expectations(projection, expected, capture)
    changed = {"capture_id": "668267be-8127-4da6-810d-d3c2b90c6fc0", "source_makerspace_id": 2,
               "source_rows_sha256": "e" * 64, "user_closure_sha256": "f" * 64}[binding]
    with pytest.raises(TenantDumpVerificationError, match="frozen source projection"):
        validate_source_expectations(projection, replace(expected, **{binding: changed}), capture)
