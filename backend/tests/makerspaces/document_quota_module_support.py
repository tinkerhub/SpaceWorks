"""Real API debits and purge custody; only the versioned provider is replaced."""
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from django.db import connection
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.document_storage_quota import proven_document_charge
from apps.makerspaces import limits, purge_storage
from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_install import uninstall_module
from apps.makerspaces.module_purge import purge_module
from apps.procurement import storage as receipt_storage
from apps.warranty import storage as warranty_storage
from apps.warranty.models import Warranty, WarrantyDocument
from tests.document_safety.helpers import (
    accepted_body, assert_storage_boundary, asset, cap, finalize, lab, presign, usage,
)
from tests.makerspaces.module_cleanup_support import ModuleStore, module_store
from tests.makerspaces.purge_test_support import actor


def missing(code="NoSuchKey", status=404):
    return ClientError({"Error": {"Code": code},
                        "ResponseMetadata": {"HTTPStatusCode": status}}, "DocumentModuleStore")


class DocumentModuleStore(ModuleStore):
    """One bucket-aware version history for conditional publication and strict purge."""

    def __init__(self):
        super().__init__()
        self.mime = {}
        self.boundary = None

    def _io(self):
        assert connection.vendor == "postgresql"
        assert connection.get_autocommit() and not connection.in_atomic_block
        if self.boundary:
            self.boundary()

    def put(self, bucket, key, payload=b"bytes", *, marker=False, mime="application/pdf"):
        identity = super().put(bucket, key, payload, marker=marker)
        self.mime[identity] = mime
        return identity

    def current(self, bucket, key):
        rows = [identity for identity in self.objects if identity[:2] == (bucket, key)]
        if not rows:
            return None
        identity = max(rows, key=lambda value: int(value[2]))
        return None if self.objects[identity][1] else identity

    def get_object(self, *, Bucket, Key):
        self._io()
        self.calls.append(("get", {"Bucket": Bucket, "Key": Key}))
        identity = self.current(Bucket, Key)
        if identity is None:
            raise missing()
        body = self.objects[identity][0]
        return {"Body": BytesIO(body), "ContentLength": len(body),
                "ContentType": self.mime[identity], "Metadata": {}, "VersionId": identity[2]}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata, IfNoneMatch):
        self._io()
        assert IfNoneMatch == "*"
        self.calls.append(("publish", {"Bucket": Bucket, "Key": Key, "IfNoneMatch": IfNoneMatch}))
        if self.current(Bucket, Key) is not None:
            raise missing("PreconditionFailed", 412)
        identity = self.put(Bucket, Key, Body.read(), mime=ContentType)
        return {"VersionId": identity[2]}

    def head_object(self, **params):
        self._io()
        result = super().head_object(**params)
        result["ContentType"] = self.mime[self.current(params["Bucket"], params["Key"])]
        return result

    def get_bucket_versioning(self, **params):
        self._io()
        self.calls.append(("versioning", params))
        return {"Status": "Enabled"}

    def list_object_versions(self, **params):
        self._io()
        return super().list_object_versions(**params)

    def delete_objects(self, *, Bucket, Delete):
        self._io()
        if Delete["Quiet"] is False:
            return super().delete_objects(Bucket=Bucket, Delete=Delete)
        assert Delete["Quiet"] is True
        assert all(set(row) == {"Key", "VersionId"} for row in Delete["Objects"])
        self.calls.append(("accepted_delete", {"Bucket": Bucket, "Delete": Delete}))
        if self.failure:
            raise missing("ServiceUnavailable", 503)
        for row in Delete["Objects"]:
            self.objects.pop((Bucket, row["Key"], row["VersionId"]), None)
        # Quiet=True suppresses success acknowledgements; strict purge never uses it.
        return {}

    def delete_object(self, **params):
        self._io()
        assert set(params) == {"Bucket", "Key", "VersionId"}
        return super().delete_object(**params)

    def generate_presigned_post(self, **params):
        self._io()
        self.calls.append(("presign", params))
        return {"url": "https://objects.example.test/upload",
                "fields": {**params["Fields"], "key": params["Key"]}}


@pytest.fixture
def local_document_identity():
    # transaction=True flushes the migration seed between cases. Seed explicitly.
    identity = DeploymentDatabaseIdentity.load()
    assert identity.database_uuid.int
    return identity


@pytest.fixture
def document_module_case(monkeypatch, settings, module_store, local_document_identity):
    settings.STORAGE_PRESIGN_METHOD = "post"
    case = lab(monkeypatch, settings)
    assert limits.is_self_host() is False
    cap(case, 1000000)
    case.store = DocumentModuleStore()
    for module in (receipt_storage, warranty_storage):
        monkeypatch.setattr(module, "_client", lambda: case.store)
        monkeypatch.setattr(module, "_public_client", lambda: case.store)
    monkeypatch.setattr(purge_storage, "client", lambda: case.store)
    case.superadmin = actor(f"quota-module-{uuid4().hex[:12]}")
    case.database_identity = local_document_identity
    return case


def publish(case, *, variant=False):
    before = usage(case)
    key, upload = presign(case)
    assert upload["fields"]["key"] == f"staging/{key}"
    body = accepted_body("application/pdf", variant=variant)
    case.store.put(purge_storage.bucket_name("private"), f"staging/{key}", body)
    case.store.boundary = lambda: assert_storage_boundary(case)
    try:
        response = finalize(case, key)
    finally:
        case.store.boundary = None
    assert response.status_code == 201, response.data
    row = case.model.objects.get(pk=response.data["id"])
    event = AuditLog.objects.get(target_type=row._meta.label_lower, target_id=str(row.pk),
                                 action=("procurement.receipt_added" if case.prefix.startswith("procurement:")
                                         else "warranty.document_added"))
    proof = proven_document_charge(row, makerspace_id=case.home.pk)
    assert proof is not None and proof.size_bytes == len(body)
    assert usage(case) == before + len(body)
    assert not case.store.has_key(purge_storage.bucket_name("private"), f"staging/{key}")
    return SimpleNamespace(row=row, key=key, body=body, event=event, proof=proof)


def warranty_case(case):
    warranty = Warranty.objects.create(makerspace=case.home, asset=asset(case.home))
    return SimpleNamespace(**{
        **vars(case), "target": warranty, "model": WarrantyDocument,
        "module": warranty_storage, "prefix": "admin-warranty-document",
        "url": reverse("admin-warranty-documents", kwargs={"pk": warranty.pk}),
    })


def disable_procurement(case):
    assert uninstall_module(case.home, "procurement", case.superadmin) == ["procurement"]
    assert "procurement" not in case.home.enabled_modules


def pending(case):
    case.store.failure = "storage"
    try:
        with pytest.raises(purge_storage.PurgeStorageRefused):
            purge_module(case.home, "procurement", case.superadmin)
    finally:
        case.store.failure = None
    receipt = ModulePurgeReceipt.objects.get(source_makerspace_id=case.home.pk)
    assert receipt.graph_purged_at is None and receipt.last_verified_at is None
    assert receipt.last_error_code == "cleanup_unconfirmed"
    return receipt


def releases(case):
    return AuditLog.objects.filter(makerspace_id=case.home.pk,
                                   action="storage.document_quota_released")


def assert_release(case, document):
    marker = releases(case).get()
    assert marker.target_type == document.row._meta.label_lower
    assert marker.target_id == str(document.row.pk)
    assert marker.meta == {**document.event.meta, "charge_event_uuid": str(document.event.event_uuid)}


def assert_unpaid(case, document, receipt, amount):
    receipt.refresh_from_db()
    assert receipt.graph_purged_at is None and receipt.last_verified_at is None
    assert case.model.objects.filter(pk=document.row.pk).exists()
    assert type(case.target).objects.filter(pk=case.target.pk).exists()
    assert usage(case) == amount and not releases(case).exists()
    assert not AuditLog.objects.filter(action="makerspace.module_purged").exists()
    document.event.refresh_from_db()
    assert document.event.meta == document.proof.metadata()


def confirmed_deletions(store):
    return {(params["Bucket"], row["Key"], row["VersionId"])
            for operation, params in store.calls if operation == "delete"
            for row in params["Delete"]["Objects"]}
