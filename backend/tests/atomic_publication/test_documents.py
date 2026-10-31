"""Resource-bound uploads and conservative retained-key claims via actual APIs."""
from unittest.mock import Mock

import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.machines import storage as machine_storage
from apps.machines.models import Machine, MachineDocument
from apps.procurement import storage as receipt_storage
from apps.procurement.models import ToBuyItem, ToBuyReceipt
from apps.warranty import storage as warranty_storage
from apps.warranty.models import Warranty, WarrantyDocument
from tests.atomic_publication.domain import bind_store, setup_machine
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db(transaction=True)
KINDS = ["machine", "warranty", "procurement"]


def case(kind, monkeypatch):
    space, actor, machine = setup_machine(f"atomic-resource-{kind}", monkeypatch)
    if kind == "machine":
        target, module, prefix = machine, machine_storage, "admin-machine-document"
        key = module.machine_object_key(space.pk, target.pk, "pdf")
        create_name, model = "admin-machine-documents", MachineDocument
        def create(key):
            return model.objects.create(machine=target, object_key=key, doc_type="manual",
                                        original_filename="legacy.pdf", content_type="application/pdf",
                                        size_bytes=9, uploaded_by=actor)
    elif kind == "warranty":
        target = Warranty.objects.create(makerspace=space, machine=machine)
        module, prefix, create_name, model = warranty_storage, "admin-warranty-document", "admin-warranty-documents", WarrantyDocument
        key = module.warranty_object_key(space.pk, target.pk, "pdf")
        def create(key):
            return model.objects.create(warranty=target, object_key=key, original_filename="legacy.pdf",
                                        content_type="application/pdf", size_bytes=9, uploaded_by=actor)
    else:
        target = ToBuyItem.objects.create(makerspace=space, kind="hardware", name="Drill")
        module, prefix, create_name, model = receipt_storage, "procurement:to-buy-receipt", "procurement:to-buy-receipt-list", ToBuyReceipt
        key = module.receipt_object_key(space.pk, target.pk, "pdf")
        def create(key):
            return model.objects.create(to_buy_item=target, object_key=key, uploaded_by=actor)
    client = authenticated_client(actor)
    payload = {"object_key": key, "doc_type": "manual", "original_filename": "manual.pdf"}
    url = reverse(create_name, kwargs={"pk": target.pk})
    return space, actor, machine, target, module, prefix, model, key, create, client, payload, url


@pytest.mark.parametrize("kind", KINDS)
def test_presign_is_bound_to_exact_resource_and_targets_staging(kind, monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "post"
    space, _actor, _machine, target, module, prefix, _model, _key, _create, client, _payload, _url = case(kind, monkeypatch)
    transport = Mock()
    transport.generate_presigned_post.return_value = {"url": "https://upload.invalid", "fields": {}}
    monkeypatch.setattr(module, "_public_client", lambda: transport)
    response = client.post(reverse(f"{prefix}-presign", kwargs={"pk": target.pk}),
                           {"filename": "manual.pdf", "content_type": "application/pdf", "doc_type": "manual"}, format="json")
    assert response.status_code == 201, response.data
    key = response.data["object_key"]
    expected = {"machine": f"machines/{space.pk}/{target.pk}/documents/",
                "warranty": f"warranty/{space.pk}/{target.pk}/documents/",
                "procurement": f"procurement/{space.pk}/{target.pk}/receipts/"}[kind]
    assert key.startswith(expected)
    assert transport.generate_presigned_post.call_args.kwargs["Key"] == f"staging/{key}"
    assert transport.generate_presigned_post.call_args.kwargs["Fields"] == {"Content-Type": "application/pdf"}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("bad_key", ["other-resource", "unclaimed-flat"])
def test_new_claim_refuses_cross_resource_or_unclaimed_legacy_flat_before_s3(kind, bad_key, monkeypatch):
    space, _actor, _machine, target, module, _prefix, model, key, _create, client, payload, url = case(kind, monkeypatch)
    store = bind_store(monkeypatch, module)
    if bad_key == "other-resource":
        # Preserve tenant and valid UUID while changing only the resource binding.
        parts = key.split("/")
        parts[2] = str(target.pk + 10000)
        key = "/".join(parts)
    else:
        key = f'{key.split("/")[0]}/{space.pk}/legacy.pdf'
    payload["object_key"] = key
    response = client.post(url, payload, format="json")
    assert response.status_code == 400, response.data
    assert model.objects.count() == 0 and store.calls == []


@pytest.mark.parametrize("kind", KINDS)
def test_matching_canonical_legacy_repeat_finalize_is_idempotent_no_io_audit_or_charge(kind, monkeypatch):
    space, _actor, _machine, _target, module, _prefix, model, key, create, client, payload, url = case(kind, monkeypatch)
    legacy = f'{key.split("/")[0]}/{space.pk}/legacy.pdf'
    row = create(legacy)
    store = bind_store(monkeypatch, module)
    payload["object_key"] = legacy
    audit_before = AuditLog.objects.count()
    used = space.storage_bytes_used
    for _ in range(2):
        response = client.post(url, payload, format="json")
        assert response.status_code == 201, response.data
        assert response.data["id"] == row.pk
    space.refresh_from_db()
    assert model.objects.count() == 1 and store.calls == []
    assert space.storage_bytes_used == used and AuditLog.objects.count() == audit_before


@pytest.mark.parametrize("kind", KINDS)
def test_retained_unrelated_private_model_blocks_new_claim_before_s3(kind, monkeypatch):
    space, actor, machine, _target, module, _prefix, model, key, _create, client, payload, url = case(kind, monkeypatch)
    if kind == "machine":
        warranty = Warranty.objects.create(makerspace=space, machine=machine)
        WarrantyDocument.objects.create(warranty=warranty, object_key=key, original_filename="retained.pdf",
                                        content_type="application/pdf", size_bytes=9, uploaded_by=actor)
    else:
        MachineDocument.objects.create(machine=machine, object_key=key, doc_type="manual",
                                       original_filename="retained.pdf", content_type="application/pdf",
                                       size_bytes=9, uploaded_by=actor)
    store = bind_store(monkeypatch, module)
    before = model.objects.count()
    response = client.post(url, payload, format="json")
    assert response.status_code == 400, response.data
    assert model.objects.count() == before and store.calls == []


@pytest.mark.parametrize("kind", KINDS)
def test_legacy_existing_row_signed_get_and_guarded_delete_still_work(kind, monkeypatch):
    space, _actor, _machine, _target, module, prefix, model, key, create, client, _payload, _url = case(kind, monkeypatch)
    legacy = f'{key.split("/")[0]}/{space.pk}/legacy.pdf'
    row = create(legacy)
    store = bind_store(monkeypatch, module)
    store.seed(legacy, b"%PDF-kept")
    transport = Mock()
    transport.generate_presigned_url.return_value = "https://download.invalid/signed"
    monkeypatch.setattr(module, "_public_client", lambda: transport)
    response = client.get(reverse(f"{prefix}-url", kwargs={"pk": row.pk}))
    assert response.status_code == 200, response.data
    assert transport.generate_presigned_url.call_args.kwargs["Params"]["Key"] == legacy
    response = client.delete(reverse(f"{prefix}-detail", kwargs={"pk": row.pk}))
    assert response.status_code == 204, getattr(response, "data", None)
    assert not model.objects.filter(pk=row.pk).exists() and legacy not in store.objects


@pytest.mark.parametrize("kind", KINDS)
def test_valid_resource_finalize_uses_real_storage_and_one_canonical_row(kind, monkeypatch):
    space, _actor, _machine, _target, module, _prefix, model, key, _create, client, payload, url = case(kind, monkeypatch)
    store = bind_store(monkeypatch, module)
    data = b"%PDF-1.7\nresource-bound document"
    store.seed(module.staging_key(key), data)
    before = AuditLog.objects.count()
    first = client.post(url, payload, format="json")
    repeated = client.post(url, payload, format="json")
    assert (first.status_code, repeated.status_code) == (201, 201)
    assert first.data["id"] == repeated.data["id"]
    assert model.objects.filter(object_key=key).count() == 1
    assert store.objects[key][:2] == (data, "application/pdf")
    assert len(store.put_bodies) == 1 and AuditLog.objects.count() == before + 1
    if kind != "procurement":
        row = model.objects.get(object_key=key)
        assert row.content_type == "application/pdf" and row.size_bytes == len(data)


@pytest.mark.parametrize("kind", ["warranty", "procurement"])
def test_unguarded_parent_cascade_refuses_before_any_object_cleanup(kind, monkeypatch):
    from apps.evidence.storage import StorageUnavailable
    _space, _actor, _machine, target, module, _prefix, model, key, create, _client, _payload, _url = case(kind, monkeypatch)
    row = create(key)
    store = bind_store(monkeypatch, module)
    store.seed(key, b"%PDF-retained")
    with pytest.raises(StorageUnavailable):
        target.delete()
    assert model.objects.filter(pk=row.pk).exists()
    assert store.calls == [] and store.objects[key][0] == b"%PDF-retained"
