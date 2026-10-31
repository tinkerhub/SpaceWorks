"""Managed obligations cannot be rebound after accounting or proof provenance drifts."""
import pytest
from django.core.exceptions import ValidationError

from apps.audit import services as audit
from apps.document_storage_quota import proven_document_charge
from apps.makerspaces import limits
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_graph import snapshot
from apps.makerspaces.module_purge_plans import BY_KEY
from apps.makerspaces.module_purge_receipts import retry_cleanup
from tests.document_safety.helpers import usage
from tests.makerspaces.document_quota_module_support import (
    assert_release, assert_unpaid, disable_procurement, document_module_case,
    local_document_identity, module_store, pending, publish, releases,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_new_selfhost_purge_ignores_historical_managed_charge(document_module_case, monkeypatch, settings):
    case = document_module_case
    document = publish(case)
    disable_procurement(case)
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    # Historical local proof remains genuine; current self-host accounting is inactive.
    assert proven_document_charge(document.row, makerspace_id=case.home.pk) == document.proof
    assert snapshot(case.home, BY_KEY["procurement"])[3] == []
    receipt, counts = purge_module(case.home, "procurement", case.superadmin)
    assert counts["receipts"] == 1 and receipt.charge_obligations == []
    assert receipt.graph_purged_at and not case.store.objects
    assert not case.model.objects.filter(pk=document.row.pk).exists()
    assert usage(case) == len(document.body) and not releases(case).exists()
    retry_cleanup(receipt.pk, case.superadmin)
    assert usage(case) == len(document.body) and not releases(case).exists()


def test_pending_managed_receipt_refuses_mode_flip_before_provider_then_original_mode_pays_once(
    document_module_case, monkeypatch, settings,
):
    case = document_module_case
    document = publish(case)
    disable_procurement(case)
    receipt = pending(case)
    frozen = receipt.graph_digest, receipt.charge_obligations
    objects = case.store.objects.copy()
    with monkeypatch.context() as patch:
        patch.setattr(limits, "is_self_host", lambda: True)
        patch.setattr(settings, "PLATFORM_DOMAIN_SUFFIX", "")
        case.store.calls.clear()
        with pytest.raises(ValidationError, match="graph changed"):
            retry_cleanup(receipt.pk, case.superadmin)
        assert case.store.calls == [] and case.store.objects == objects
        assert_unpaid(case, document, receipt, len(document.body))
        assert (receipt.graph_digest, receipt.charge_obligations) == frozen
    completed = retry_cleanup(receipt.pk, case.superadmin)
    assert completed.pk == receipt.pk and completed.graph_purged_at
    assert usage(case) == 0
    assert_release(case, document)
    retry_cleanup(receipt.pk, case.superadmin)
    assert usage(case) == 0 and releases(case).count() == 1


def test_pending_receipt_refuses_ambiguous_original_provenance_before_provider(document_module_case):
    case = document_module_case
    document = publish(case)
    disable_procurement(case)
    receipt = pending(case)
    # Append a conflicting NEGATIVE marker; never modify the immutable original event.
    audit.record(case.actor, "procurement.receipt_added", makerspace=case.home,
                 target=document.row, meta={"version": 1, "bytes": False})
    assert proven_document_charge(document.row, makerspace_id=case.home.pk) is None
    objects = case.store.objects.copy()
    case.store.calls.clear()
    with pytest.raises(ValidationError, match="graph changed"):
        retry_cleanup(receipt.pk, case.superadmin)
    assert case.store.calls == [] and case.store.objects == objects
    assert_unpaid(case, document, receipt, len(document.body))
