"""DB settlement failures preserve payable authority after irreversible byte cleanup."""
import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.makerspaces import module_purge_receipts
from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_storage import bucket_name
from tests.document_safety.helpers import usage
from tests.makerspaces.document_quota_module_support import (
    assert_release, assert_unpaid, disable_procurement, document_module_case,
    local_document_identity, module_store, publish, releases, warranty_case,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("phase", ["release_marker", "checkpoint"])
def test_failure_after_real_release_or_checkpoint_rolls_back_and_empty_retry_pays_once(
    phase, document_module_case, monkeypatch,
):
    case = document_module_case
    document = publish(case)
    unrelated = publish(warranty_case(case), variant=True)
    total = len(document.body) + len(unrelated.body)
    disable_procurement(case)
    observed = []
    with monkeypatch.context() as patch:
        if phase == "release_marker":
            original = module_purge_receipts.audit.record

            def crash_after_release(actor, action, **kwargs):
                result = original(actor, action, **kwargs)
                if action == "storage.document_quota_released":
                    assert_release(case, document)
                    assert usage(case) == len(unrelated.body)
                    assert not case.model.objects.filter(pk=document.row.pk).exists()
                    observed.append(result.pk)
                    raise RuntimeError("after real release INSERT and counter UPDATE")
                return result

            patch.setattr(module_purge_receipts.audit, "record", crash_after_release)
        else:
            original = ModulePurgeReceipt.save

            def crash_after_checkpoint(self, *args, **kwargs):
                result = original(self, *args, **kwargs)
                if self.graph_purged_at is not None:
                    assert ModulePurgeReceipt.objects.get(pk=self.pk).graph_purged_at is not None
                    assert usage(case) == len(unrelated.body)
                    assert_release(case, document)
                    observed.append(self.pk)
                    raise RuntimeError("after real checkpoint UPDATE")
                return result

            patch.setattr(ModulePurgeReceipt, "save", crash_after_checkpoint)
        with pytest.raises(RuntimeError, match="after real"):
            purge_module(case.home, "procurement", case.superadmin)
    receipt = ModulePurgeReceipt.objects.get(source_makerspace_id=case.home.pk)
    assert observed
    assert_unpaid(case, document, receipt, total)
    assert receipt.last_error_code == "cleanup_unconfirmed"
    assert not case.store.has_key(bucket_name("private"), document.key)
    assert case.store.has_key(bucket_name("private"), unrelated.key)
    frozen = (receipt.graph_digest, receipt.charge_obligations, receipt.holder_sites)
    deleted = list(case.store.deletes)
    completed = retry_cleanup(receipt.pk, case.superadmin)
    assert completed.graph_purged_at and completed.last_verified_at
    assert (completed.graph_digest, completed.charge_obligations, completed.holder_sites) == frozen
    assert case.store.deletes == deleted, "retry must settle original proof when bytes are already absent"
    assert usage(case) == len(unrelated.body)
    assert_release(case, document)
    assert not case.model.objects.filter(pk=document.row.pk).exists()
    retry_cleanup(receipt.pk, case.superadmin)
    assert usage(case) == len(unrelated.body) and releases(case).count() == 1
    assert AuditLog.objects.filter(action="makerspace.module_purged").count() == 1


def test_negative_release_result_refuses_unpaid_checkpoint(document_module_case, monkeypatch):
    from apps import document_storage_quota

    case = document_module_case
    document = publish(case)
    disable_procurement(case)
    called = []

    def refused(proof, *, verify):
        # A negative helper-return fault only: never fabricate successful settlement.
        verify()
        assert proof == document.proof
        assert not case.model.objects.filter(pk=document.row.pk).exists()
        called.append(proof)
        return False

    with monkeypatch.context() as patch:
        patch.setattr(document_storage_quota, "release_charge_once", refused)
        with pytest.raises(ValidationError, match="settled exactly once"):
            purge_module(case.home, "procurement", case.superadmin)
    receipt = ModulePurgeReceipt.objects.get(source_makerspace_id=case.home.pk)
    assert called == [document.proof]
    assert_unpaid(case, document, receipt, len(document.body))
    assert not case.store.has_key(bucket_name("private"), document.key)
    retry_cleanup(receipt.pk, case.superadmin)
    assert usage(case) == 0
    assert_release(case, document)
    retry_cleanup(receipt.pk, case.superadmin)
    assert usage(case) == 0 and releases(case).count() == 1
