"""Functional portable projection/remap and raw sanitization of local audit facts."""
from copy import deepcopy

import pytest
from django.db import transaction

from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.backup.raw_projection import raw_records
from apps.data_export.reference_provenance import ReferenceProvenanceWriter
from apps.document_storage_quota import proven_document_charge
from apps.tenant_migration.audit_references import AUDIT_META_REFERENCES, AuditReferenceDisposition
from apps.tenant_migration.pk_maps import TransactionPkMap
from apps.tenant_migration.raw_repository import RawImportRepository
from apps.tenant_migration.semantic_remap import remap_semantic_references
from apps.tenant_migration.tenant_dump_raw import sanitize_record
from tests.document_safety.helpers import cap, lab, usage
from tests.document_quota.helpers import KINDS, clear_identity, delete, legacy_row, releases, upload

pytestmark = pytest.mark.django_db(transaction=True)


def project(event, root):
    writer = ReferenceProvenanceWriter(root, event.makerspace_id)
    source = raw_records(AuditLog.objects.filter(pk=event.pk), AuditLog)[0]
    try:
        writer.prepare_rows("audit.AuditLog", [event])
        for field in ("meta", "target_type", "target_id"):
            source[field] = writer.project(event, field, source[field])
        assert writer.project(event, "meta", source["meta"]) == source["meta"]
    finally:
        writer.close()
    return source


def import_event(source, target_case, target):
    # Functional production PK mapping and insert; no audit UPDATE/trigger bypass.
    with transaction.atomic():
        pk_map = TransactionPkMap()
        pk_map.add_many(type(target), [(source["target_id"], target.pk)])
        pk_map.reserve(AuditLog, [source["id"]])
        row = dict(source)
        row["meta"] = deepcopy(source["meta"])
        row.update(id=pk_map.lookup(AuditLog, source["id"]),
                   makerspace_id=target_case.home.pk, event_uuid=None, row_mac=None)
        assert remap_semantic_references("audit.AuditLog", source, row, pk_map, None)
        assert RawImportRepository().insert_rows(AuditLog, [row]) == 1
    return AuditLog.objects.get(pk=row["id"])


@pytest.mark.parametrize("kind", KINDS)
def test_real_added_proof_is_source_namespaced_on_portable_remap_and_cannot_refund(
    kind, monkeypatch, settings, tmp_path,
):
    source_case = lab(monkeypatch, settings, kind)
    row, event, body = upload(source_case)
    edge = (event.action, "accounting_database_id")
    assert AUDIT_META_REFERENCES[edge].disposition is AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT
    projected = project(event, tmp_path)
    assert projected["meta"] == event.meta | {
        "accounting_database_id": "source:" + event.meta["accounting_database_id"],
    }
    assert (tmp_path / "migration/reference_provenance.jsonl").read_text() == ""
    target_case = lab(monkeypatch, settings, kind)
    cap(target_case, 1000000, used=900)
    target = legacy_row(target_case)
    target_case.store.seed(target.object_key, body)
    imported = import_event(projected, target_case, target)
    assert imported.target_id == str(target.pk) and target.pk != row.pk
    assert imported.target_type == target._meta.label_lower and imported.actor_id is None
    assert imported.makerspace_id == target_case.home.pk and imported.meta == projected["meta"]
    assert proven_document_charge(target, makerspace_id=target_case.home.pk) is None
    assert delete(target_case, target).status_code == 204
    assert usage(target_case) == 900 and not releases(target_case).exists()
    assert usage(source_case) == len(body)


@pytest.mark.parametrize("kind", KINDS)
def test_actual_release_projection_namespaces_both_local_identifiers_and_remaps_target(
    kind, monkeypatch, settings, tmp_path,
):
    case = lab(monkeypatch, settings, kind)
    row, charge, _ = upload(case)
    original_pk = row.pk
    assert delete(case, row).status_code == 204
    release = releases(case).get()
    assert release.target_id == str(original_pk)
    for field in ("accounting_database_id", "charge_event_uuid"):
        assert AUDIT_META_REFERENCES[(release.action, field)].disposition is AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT
    projected = project(release, tmp_path)
    assert projected["meta"] == release.meta | {
        "accounting_database_id": "source:" + charge.meta["accounting_database_id"],
        "charge_event_uuid": "source:" + str(charge.event_uuid),
    }
    target_case = lab(monkeypatch, settings, kind)
    target = legacy_row(target_case)
    imported = import_event(projected, target_case, target)
    assert imported.meta == projected["meta"] and imported.target_id == str(target.pk)
    assert imported.actor_id is None and usage(target_case) == 0


@pytest.mark.parametrize("kind", KINDS)
def test_raw_snapshot_sanitizer_preserves_facts_but_foreign_database_identity_is_inert(
    kind, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    row, event, _ = upload(case)
    original = raw_records(AuditLog.objects.filter(pk=event.pk), AuditLog)[0]
    sanitized = sanitize_record(AuditLog, original)
    assert sanitized.values["meta"] == event.meta
    assert sanitized.values["event_uuid"] is None and sanitized.values["row_mac"] is None
    assert sanitized.values["target_id"] == str(row.pk)
    assert proven_document_charge(row, makerspace_id=case.home.pk) is not None
    clear_identity()
    target_identity = DeploymentDatabaseIdentity.objects.create(pk=1)
    assert str(target_identity.database_uuid) != event.meta["accounting_database_id"]
    assert proven_document_charge(row, makerspace_id=case.home.pk) is None
    event.refresh_from_db()
    assert event.meta == original["meta"]  # Sanitizing never mutates retained audit.
