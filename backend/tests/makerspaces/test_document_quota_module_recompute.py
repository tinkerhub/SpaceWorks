"""The actual reconciler preserves proven debits before a pending procurement purge."""
from io import StringIO

import pytest
from django.core.management import call_command

from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_storage import bucket_name
from apps.procurement import storage as receipt_storage
from apps.warranty import storage as warranty_storage
from apps.warranty.models import WarrantyDocument
from tests.document_safety.helpers import usage
from tests.makerspaces.document_quota_module_support import (
    assert_release, disable_procurement, document_module_case, local_document_identity,
    module_store, pending, publish, releases, warranty_case,
)
from tests.makerspaces.module_cleanup_support import seed_versions

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("head", ["delete_marker", "smaller", "larger"])
def test_command_then_pending_purge_preserves_proven_debits_and_unrelated_warranty(
    head, document_module_case,
):
    case = document_module_case
    document = publish(case)
    unrelated = publish(warranty_case(case), variant=True)
    total = len(document.body) + len(unrelated.body)
    bucket = bucket_name("private")
    for accepted in (document, unrelated):
        seed_versions(case.store, "private", accepted.key, accepted.body)
        if head == "smaller":
            case.store.put(bucket, accepted.key, b"x")
        elif head == "larger":
            case.store.put(bucket, accepted.key, accepted.body * 3)
    expected_head = {"delete_marker": None, "smaller": 1, "larger": len(document.body) * 3}[head]
    assert receipt_storage.object_size(document.key) == expected_head
    warranty_head = {"delete_marker": None, "smaller": 1, "larger": len(unrelated.body) * 3}[head]
    assert warranty_storage.object_size(unrelated.key) == warranty_head
    unrelated_versions = {identity: value for identity, value in case.store.objects.items()
                          if identity[1] in {unrelated.key, f"staging/{unrelated.key}"}}
    assert not ModulePurgeReceipt.objects.exists()
    output = StringIO()
    # Real command, source exclusion, proof reads and SQL counter commit.
    call_command("recompute_storage", str(case.home.pk), stdout=output)
    assert f"total={total} bytes" in output.getvalue()
    assert usage(case) == total and not releases(case).exists()
    disable_procurement(case)
    receipt = pending(case)
    assert receipt.charge_obligations == [[
        f"procurement:{document.row.pk}:{document.event.event_uuid}",
        "private", document.key, len(document.body),
    ]]
    assert usage(case) == total
    completed = retry_cleanup(receipt.pk, case.superadmin)
    assert completed.graph_purged_at
    assert usage(case) == len(unrelated.body)
    assert not case.model.objects.filter(pk=document.row.pk).exists()
    assert not type(case.target).objects.filter(pk=case.target.pk).exists()
    assert not case.store.has_key(bucket, document.key)
    assert not case.store.has_key(bucket, f"staging/{document.key}")
    assert WarrantyDocument.objects.filter(pk=unrelated.row.pk).exists()
    assert all(case.store.objects[identity] == value for identity, value in unrelated_versions.items())
    assert_release(case, document)
    retry_cleanup(receipt.pk, case.superadmin)
    assert usage(case) == len(unrelated.body) and releases(case).count() == 1
