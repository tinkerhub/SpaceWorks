"""Reject malformed frozen locators and revalidate every refund against real audit proof."""
from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.makerspaces import module_purge_receipts
from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_receipt_authority import validate_receipt
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_storage import PurgeStorageRefused, bucket_name
from tests.document_safety.helpers import snapshot, usage
from tests.makerspaces.document_quota_module_support import (
    assert_release, assert_unpaid, disable_procurement, document_module_case,
    local_document_identity, module_store, pending, publish, releases, warranty_case,
)

pytestmark = pytest.mark.django_db(transaction=True)


def malformed_copy(receipt, fault):
    copy = deepcopy(receipt)  # Never saved: persisted immutable authority stays intact.
    obligation = copy.charge_obligations[0]
    pk, event = obligation[0].split(":")[1:]
    if fault == "wrong_pk":
        obligation[0] = f"procurement:{int(pk) + 1}:{event}"
    elif fault == "zero_pk":
        obligation[0] = f"procurement:0:{event}"
    elif fault == "source_pk":
        obligation[0] = f"procurement:source-{pk}:{event}"
    elif fault == "wrong_key":
        # In exact_keys, but not the accepted typed holder's final key.
        obligation[2] = f"staging/{obligation[2]}"
    elif fault == "wrong_model":
        copy.holder_sites[0][0] = "warranty.WarrantyDocument"
    elif fault == "wrong_bucket":
        obligation[1] = "public_image"
    elif fault in {"uuid_noncanonical", "uuid_zero", "uuid_source"}:
        value = {"uuid_noncanonical": "ABCDEFAB-1234-4234-8234-123456789ABC",
                 "uuid_zero": str(UUID(int=0)), "uuid_source": f"source:{event}"}[fault]
        obligation[0] = f"procurement:{pk}:{value}"
    elif fault in {"amount_zero", "amount_negative", "amount_bool"}:
        obligation[3] = {"amount_zero": 0, "amount_negative": -1, "amount_bool": True}[fault]
    elif fault == "duplicate_physical":
        another = obligation.copy()
        another[0] = f"procurement:{pk}:{uuid4()}"
        copy.charge_obligations.append(another)
    else:
        raise AssertionError(f"Unknown test input {fault}")
    return copy


@pytest.mark.parametrize("fault", [
    "wrong_pk", "zero_pk", "source_pk", "wrong_key", "wrong_model", "wrong_bucket",
    "uuid_noncanonical", "uuid_zero", "uuid_source", "amount_zero", "amount_negative",
    "amount_bool", "duplicate_physical",
])
def test_unsaved_obligation_copies_refuse_grammar_or_holder_confusion_without_mutation(
    fault, document_module_case,
):
    case = document_module_case
    publish(case)
    disable_procurement(case)
    receipt = pending(case)
    before = (snapshot(case), list(ModulePurgeReceipt.objects.values()),
              deepcopy(case.store.objects), list(case.store.calls))
    with pytest.raises(PurgeStorageRefused):
        validate_receipt(malformed_copy(receipt, fault))
    assert (snapshot(case), list(ModulePurgeReceipt.objects.values()),
            case.store.objects, case.store.calls) == before


@pytest.mark.parametrize("fault", ["wrong_positive_amount", "wrong_event", "foreign_event"])
def test_settlement_revalidates_unsaved_handoff_against_original_audit_after_graph_delete(
    fault, document_module_case, monkeypatch,
):
    case = document_module_case
    document = publish(case)
    unrelated = publish(warranty_case(case), variant=True)
    total = len(document.body) + len(unrelated.body)
    disable_procurement(case)
    original = module_purge_receipts.settle
    observed = []

    def corrupted_handoff(space, receipt, *, verify):
        verify()
        assert not case.model.objects.filter(pk=document.row.pk).exists()
        copy = deepcopy(receipt)
        if fault == "wrong_positive_amount":
            copy.charge_obligations[0][3] += 1
        else:
            event = uuid4() if fault == "wrong_event" else unrelated.event.event_uuid
            copy.charge_obligations[0][0] = f"procurement:{document.row.pk}:{event}"
        # Canonical syntax alone cannot establish an actual debit.
        validate_receipt(copy)
        observed.append(copy.charge_obligations)
        return original(space, copy, verify=verify)

    with monkeypatch.context() as patch:
        patch.setattr(module_purge_receipts, "settle", corrupted_handoff)
        with pytest.raises(ValidationError, match="provenance|settled exactly once"):
            purge_module(case.home, "procurement", case.superadmin)
    receipt = ModulePurgeReceipt.objects.get(source_makerspace_id=case.home.pk)
    assert observed
    assert_unpaid(case, document, receipt, total)
    assert receipt.charge_obligations == [[
        f"procurement:{document.row.pk}:{document.event.event_uuid}",
        "private", document.key, len(document.body),
    ]]
    assert not case.store.has_key(bucket_name("private"), document.key)
    retry_cleanup(receipt.pk, case.superadmin)
    assert usage(case) == len(unrelated.body)
    assert_release(case, document)


@pytest.mark.parametrize("fault", ["foreign_database", "foreign_origin", "source_event", "source_target"])
def test_real_release_rejects_nonlocal_or_portable_proof_handoff_without_credit(
    fault, document_module_case, monkeypatch,
):
    from apps import document_storage_quota

    case = document_module_case
    document = publish(case)
    disable_procurement(case)
    original = document_storage_quota.release_charge_once
    observed = []

    def corrupt_proof_handoff(proof, *, verify):
        assert proof == document.proof
        changes = {
            "foreign_database": {"accounting_database_id": str(uuid4())},
            "foreign_origin": {"storage_origin": "f" * 64 if proof.storage_origin != "f" * 64 else "e" * 64},
            "source_event": {"charge_event_uuid": f"source:{proof.charge_event_uuid}"},
            "source_target": {"target_id": f"source:{proof.target_id}"},
        }[fault]
        # A tampered in-memory handoff, never a manufactured positive audit proof.
        refused = original(replace(proof, **changes), verify=verify)
        assert refused is False
        observed.append(refused)
        return refused

    with monkeypatch.context() as patch:
        patch.setattr(document_storage_quota, "release_charge_once", corrupt_proof_handoff)
        with pytest.raises(ValidationError, match="settled exactly once"):
            purge_module(case.home, "procurement", case.superadmin)
    receipt = ModulePurgeReceipt.objects.get(source_makerspace_id=case.home.pk)
    assert observed == [False]
    assert_unpaid(case, document, receipt, len(document.body))
    assert AuditLog.objects.filter(pk=document.event.pk).count() == 1
    retry_cleanup(receipt.pk, case.superadmin)
    assert usage(case) == 0
    assert_release(case, document)
    retry_cleanup(receipt.pk, case.superadmin)
    assert usage(case) == 0 and releases(case).count() == 1
