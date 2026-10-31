"""Finite API charges survive byte-first purge and refund only their own debit."""
from hashlib import sha256
from uuid import UUID

import pytest

from apps.audit.models import AuditLog
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_intent import storage_origins
from apps.makerspaces.purge_storage import bucket_name
from apps.warranty.models import WarrantyDocument
from tests.document_safety.helpers import usage
from tests.makerspaces.document_quota_module_support import (
    assert_release, confirmed_deletions, disable_procurement, document_module_case,
    local_document_identity, module_store, publish, releases, warranty_case,
)
from tests.makerspaces.module_cleanup_support import seed_versions

pytestmark = pytest.mark.django_db(transaction=True)


def test_api_charge_becomes_exact_obligation_and_strict_purge_refunds_once(document_module_case):
    case = document_module_case
    receipt_doc = publish(case)
    warranty_doc = publish(warranty_case(case), variant=True)
    event_uuid = str(receipt_doc.event.event_uuid)
    assert UUID(event_uuid).int and str(UUID(event_uuid)) == event_uuid
    assert receipt_doc.event.meta == {
        "version": 1, "bytes": len(receipt_doc.body),
        "accounting_database_id": str(case.database_identity.database_uuid),
        "storage_origin": storage_origins()["private"],
        "object_key_sha256": sha256(receipt_doc.key.encode()).hexdigest(),
        "row_created_at": receipt_doc.row.created_at.isoformat(),
    }
    assert any(op == "publish" and params["Key"] == receipt_doc.key for op, params in case.store.calls)
    assert any(op == "accepted_delete" for op, _ in case.store.calls)
    # Include historical data, staging versions and a current delete marker.
    seed_versions(case.store, "private", receipt_doc.key, receipt_doc.body)
    expected = {identity for identity in case.store.objects
                if identity[1] in {receipt_doc.key, f"staging/{receipt_doc.key}"}}
    unrelated = {identity: value for identity, value in case.store.objects.items()
                 if identity[1] == warranty_doc.key}
    disable_procurement(case)
    result, counts = purge_module(case.home, "procurement", case.superadmin)
    assert result.charge_obligations == [[
        f"procurement:{receipt_doc.row.pk}:{event_uuid}", "private",
        receipt_doc.key, len(receipt_doc.body),
    ]]
    assert result.holder_sites == [[
        "procurement.ToBuyReceipt", str(receipt_doc.row.pk), "object_key", "private", receipt_doc.key,
    ]]
    assert result.graph_purged_at and result.last_verified_at
    assert counts["receipts"] == 1 and counts["to_buy_items"] == 1
    assert expected <= confirmed_deletions(case.store)
    assert not case.model.objects.filter(pk=receipt_doc.row.pk).exists()
    assert not type(case.target).objects.filter(pk=case.target.pk).exists()
    assert not case.store.has_key(bucket_name("private"), receipt_doc.key)
    assert not case.store.has_key(bucket_name("private"), f"staging/{receipt_doc.key}")
    assert WarrantyDocument.objects.filter(pk=warranty_doc.row.pk).exists()
    assert all(case.store.objects[identity] == value for identity, value in unrelated.items())
    assert usage(case) == len(warranty_doc.body)
    assert_release(case, receipt_doc)
    before = list(case.store.deletes)
    assert retry_cleanup(result.pk, case.superadmin).pk == result.pk
    retried, counts = purge_module(case.home, "procurement", case.superadmin)
    assert retried.pk == result.pk and counts == {}
    assert case.store.deletes == before
    assert usage(case) == len(warranty_doc.body) and releases(case).count() == 1
    assert AuditLog.objects.filter(action="makerspace.module_purged").count() == 1
