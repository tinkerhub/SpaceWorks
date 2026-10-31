"""Cleanup history stays inert when its source rows cannot travel with a tenant."""

from uuid import UUID

import pytest

from apps.audit.models import AuditLog
from apps.data_export.reference_provenance import ReferenceProvenanceWriter
from apps.machines.models import Machine, MachineDocument, MachineType
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.audit_references import (
    AUDIT_META_REFERENCES,
    AuditReferenceDisposition,
)
from apps.tenant_migration.semantic_remap import remap_semantic_references


pytestmark = pytest.mark.django_db


class RejectPkLookup:
    def lookup(self, model, source_id):
        raise AssertionError(f"Historical snapshot tried live lookup: {model}, {source_id}")


def assert_snapshot_round_trip(log, field, model_label, tmp_path):
    rule = AUDIT_META_REFERENCES[(log.action, field)]
    assert rule.disposition is AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT
    assert rule.target_model_label == model_label
    original_meta = log.meta.copy()
    writer = ReferenceProvenanceWriter(tmp_path, log.makerspace_id)
    try:
        writer.prepare_rows("audit.AuditLog", [log])
        projected = writer.project(log, "meta", log.meta)
        assert projected == {field: f"source:{original_meta[field]}"}
        assert writer.project(log, "meta", projected) == projected
    finally:
        writer.close()

    row = {
        "action": log.action,
        "actor_id": None,
        "target_type": "",
        "target_id": "",
        "meta": projected.copy(),
    }
    assert remap_semantic_references(
        "audit.AuditLog", {"id": log.pk}, row, RejectPkLookup(), None
    ) is True
    assert row["meta"] == projected
    log.refresh_from_db()
    assert log.meta == original_meta


@pytest.mark.parametrize(
    "action",
    ["machine.document_added", "machine.document_removed"],
    ids=["added-history-after-document-deletion", "removed-history-after-document-deletion"],
)
def test_deleted_document_history_is_source_local(action, tmp_path):
    space = Makerspace.objects.create(name="Historical docs", slug="historical-docs")
    machine_type = MachineType.objects.create(
        makerspace=space, name="Historical machine", slug="historical-machine"
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Historical machine"
    )
    document = MachineDocument.objects.create(
        machine=machine,
        doc_type=MachineDocument.DocType.MANUAL,
        object_key=f"machines/{space.pk}/manual.pdf",
        original_filename="manual.pdf",
        content_type="application/pdf",
    )
    document_id = document.pk
    log = AuditLog.objects.create(
        makerspace=space, action=action, meta={"document_id": document_id}
    )
    document.delete()

    assert not MachineDocument.objects.filter(pk=document_id).exists()
    assert AuditLog.objects.filter(pk=log.pk).exists()
    assert_snapshot_round_trip(
        log, "document_id", "machines.MachineDocument", tmp_path
    )


def test_deployment_local_purge_receipt_history_is_source_local(tmp_path):
    space = Makerspace.objects.create(name="Receipt history", slug="receipt-history")
    # Receipt authority belongs to the source deployment and is absent from the
    # tenant archive; the audit row retains only its historical UUID.
    receipt_id = UUID("93acf575-330c-4d6c-a604-243d53327758")
    log = AuditLog.objects.create(
        makerspace=space,
        action="makerspace.purge_receipt_checked",
        meta={"receipt_id": str(receipt_id)},
    )

    assert_snapshot_round_trip(
        log, "receipt_id", "makerspaces.PurgeReceipt", tmp_path
    )
