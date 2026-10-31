"""Native Warranty/ToBuy audit extension only; stale-host races live elsewhere."""
from types import SimpleNamespace

import pytest
from django.db import connection
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.machines.models import Machine, MachineType
from apps.procurement import storage as receipt_storage
from apps.procurement.models import ToBuyItem, ToBuyReceipt
from apps.warranty import storage as warranty_storage
from apps.warranty.models import Warranty, WarrantyDocument
from tests.atomic_publication.store import Store
from tests.qr_target_safety_helpers import (
    fail_after_insert, native_client, native_form, qr_lab, snapshot, superadmin, target,
)
from tests.tenant_migration.source_gate_helpers import close_gate

# Native deletion acquires a dedicated storage guard before Django's change/delete
# transaction. A test-wide atomic block would itself violate that production contract.
pytestmark = pytest.mark.django_db(transaction=True)
DOCUMENT_MODELS = (Warranty, WarrantyDocument, ToBuyItem, ToBuyReceipt, Machine, MachineType)


@pytest.fixture(params=["warranty-asset", "warranty-machine", "to-buy"])
def document_case(qr_lab, request):
    actor = superadmin()
    client = native_client(actor)
    if request.param == "to-buy":
        model, name = ToBuyItem, "procurement_tobuyitem"
        changes = {"makerspace": qr_lab.home.pk, "kind": "hardware", "name": "Audit drill",
                   "quantity": "1", "status": "requested", "vendor_name": "Private vendor"}
        edited = {"vendor_name": "Changed private vendor", "status": "ordered"}
        required = {"makerspace", "kind", "name", "vendor_name"}
    else:
        model, name = Warranty, "warranty_warranty"
        host_kind = request.param.removeprefix("warranty-")
        if host_kind == "asset":
            host = target(qr_lab.home, "asset")
        else:
            machine_type = MachineType.objects.create(makerspace=qr_lab.home, name="Laser", slug="audit-laser")
            host = Machine.objects.create(makerspace=qr_lab.home, machine_type=machine_type, name="Audit laser")
        changes = {"makerspace": qr_lab.home.pk, host_kind: host.pk,
                   "vendor_name": "Private vendor", "vendor_contact": "private-contact@example.test"}
        edited = {"vendor_name": "Changed private vendor", "vendor_contact": "new-private-contact@example.test"}
        required = {"makerspace", host_kind, "vendor_name", "vendor_contact"}
    return SimpleNamespace(
        lab=qr_lab, actor=actor, client=client, model=model, name=name, changes=changes,
        edited=edited, required=required,
    )


def add(case):
    url, data = native_form(case.client, case.name, **case.changes)
    response = case.client.post(url, data)
    assert response.status_code == 302, getattr(response, "context", None)
    return case.model.objects.get()


def assert_audit(case, obj, action, fields=None):
    row = AuditLog.objects.get(action=action, target_type=obj._meta.label_lower, target_id=str(obj.pk))
    assert (row.actor_id, row.makerspace_id) == (case.actor.pk, case.lab.home.pk)
    assert set(row.meta) == {"model", "changed_fields", "detail"}
    assert row.meta["model"] == obj._meta.label_lower and row.meta["detail"] == {}
    changed = row.meta["changed_fields"]
    assert changed == sorted(set(changed))
    if fields is not None:
        assert changed == sorted(fields)
    else:
        assert case.required <= set(changed)
        assert set(changed) <= {field.name for field in obj._meta.fields}
    for secret in ("Private vendor", "Changed private vendor", "private-contact@example.test",
                   "new-private-contact@example.test"):
        assert secret not in str(row.meta)
    return row


def attach_document(case, obj):
    if case.model is Warranty:
        module, model = warranty_storage, WarrantyDocument
        key = module.warranty_object_key(case.lab.home.pk, obj.pk, "pdf")
        doc = model.objects.create(warranty=obj, object_key=key, original_filename="bill.pdf",
                                   content_type="application/pdf", size_bytes=4, uploaded_by=case.actor)
    else:
        module, model = receipt_storage, ToBuyReceipt
        key = module.receipt_object_key(case.lab.home.pk, obj.pk, "pdf")
        doc = model.objects.create(to_buy_item=obj, object_key=key, uploaded_by=case.actor)
    return module, model, doc, key


def test_actual_native_add_and_edit_audits_identify_actor_tenant_target_and_field_names(document_case):
    case = document_case
    obj = add(case)
    assert_audit(case, obj, "control.object_created")
    url, data = native_form(case.client, case.name, obj, **case.edited)
    assert case.client.post(url, data).status_code == 302
    obj.refresh_from_db()
    for key, value in case.edited.items():
        assert getattr(obj, key) == value
    assert_audit(case, obj, "control.object_updated", case.edited)
    if case.model is ToBuyItem:
        # Procurement's post-save status stamping still runs after the audit mixin.
        assert obj.purchaser_id == case.actor.pk and obj.ordered_at is not None


def test_native_noop_save_suppresses_audit_even_if_admin_updates_timestamp(document_case):
    case = document_case
    obj = add(case)
    before = list(AuditLog.objects.order_by("pk").values())
    original = case.model.objects.filter(pk=obj.pk).values().get()
    url, data = native_form(case.client, case.name, obj)
    assert case.client.post(url, data).status_code == 302
    current = case.model.objects.filter(pk=obj.pk).values().get()
    assert {key: value for key, value in current.items() if key != "updated_at"} == {
        key: value for key, value in original.items() if key != "updated_at"
    }
    assert list(AuditLog.objects.order_by("pk").values()) == before


@pytest.mark.parametrize("operation", ["add", "edit"])
def test_real_native_audit_insert_failure_rolls_back_complete_save(document_case, monkeypatch, operation):
    case = document_case
    obj = add(case) if operation == "edit" else None
    changes = case.edited if obj else case.changes
    url, data = native_form(case.client, case.name, obj, **changes)
    action = "control.object_updated" if obj else "control.object_created"
    inserted = fail_after_insert(monkeypatch, action)
    before = snapshot(*DOCUMENT_MODELS)
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        case.client.post(url, data)
    assert len(inserted) == 1
    assert not AuditLog.objects.filter(pk=inserted[0]).exists()
    assert snapshot(*DOCUMENT_MODELS) == before


@pytest.mark.parametrize("operation", ["add", "edit", "delete"])
def test_native_document_source_gate_precedes_audit_and_mutation(document_case, operation):
    case = document_case
    obj = add(case) if operation != "add" else None
    if operation == "delete":
        attach_document(case, obj)
        url, data = reverse(f"admin:{case.name}_delete", args=[obj.pk]), {"post": "yes"}
    else:
        url, data = native_form(case.client, case.name, obj, **(case.edited if obj else case.changes))
    close_gate(case.lab.home, case.actor)
    before = snapshot(*DOCUMENT_MODELS)
    response = case.client.post(url, data)
    assert response.status_code == 423
    assert snapshot(*DOCUMENT_MODELS) == before


def test_native_delete_audit_refusal_retains_parent_and_document_without_cleanup(document_case, monkeypatch):
    case = document_case
    obj = add(case)
    attach_document(case, obj)
    inserted = fail_after_insert(monkeypatch, "control.object_deleted")
    before = snapshot(*DOCUMENT_MODELS)
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        case.client.post(reverse(f"admin:{case.name}_delete", args=[obj.pk]), {"post": "yes"})
    assert len(inserted) == 1
    assert snapshot(*DOCUMENT_MODELS) == before


def test_native_audited_parent_delete_preserves_document_cleanup_wrapper(document_case, monkeypatch):
    case = document_case
    obj = add(case)
    module, model, doc, key = attach_document(case, obj)

    def assert_cleanup_guards():
        assert connection.get_autocommit() and not connection.in_atomic_block
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT classid, mode FROM pg_locks WHERE locktype='advisory' "
                "AND objid=%s AND objsubid=2 AND granted AND pid<>pg_backend_pid()",
                [case.lab.home.pk],
            )
            held = set(cursor.fetchall())
        assert (734310, "ShareLock") in held and (734312, "ExclusiveLock") in held

    store = Store(boundary=assert_cleanup_guards)
    store.seed(key, b"bill")
    store.seed(key, b"new bill")
    survivor_key = key + ".unrelated"
    store.seed(survivor_key, b"keep")
    monkeypatch.setattr(module, "_client", lambda: store)
    object_id, doc_id = obj.pk, doc.pk
    response = case.client.post(reverse(f"admin:{case.name}_delete", args=[object_id]), {"post": "yes"})
    assert response.status_code == 302
    assert not case.model.objects.filter(pk=object_id).exists()
    assert not model.objects.filter(pk=doc_id).exists()
    assert store.calls
    assert not store.versions[key]
    assert store.objects[survivor_key][0] == b"keep"
    assert AuditLog.objects.filter(
        action="control.object_deleted", actor=case.actor, makerspace=case.lab.home,
        target_type=case.model._meta.label_lower, target_id=str(object_id),
    ).count() == 1
