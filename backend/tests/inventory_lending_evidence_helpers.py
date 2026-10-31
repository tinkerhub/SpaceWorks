"""Uploaded-image transport and durable domain snapshots; no validator bypasses."""
from apps.audit.models import AuditLog
from apps.boxes.models import BoxScan, QrScanEvent
from apps.evidence import storage
from apps.evidence.models import EvidencePhoto, EvidenceUploadFinalization
from apps.evidence.storage import (
    object_exists as real_object_exists,
    validate_evidence_object as real_validate_evidence_object,
)
from apps.hardware_requests.models import (
    HardwareRequest, HardwareRequestItem, HardwareRequestItemAsset,
    RequesterAccountability, ReturnEvent,
)
from apps.inventory.models import InventoryAsset, InventoryProduct
from tests.atomic_publication.store import Store, png
from tests.return_helpers import make_issue_evidence, make_return_evidence


class EvidenceStore(Store):
    """Evidence's canonical promotion uses COPY; retain Store's versioned semantics."""

    def copy_object(self, **kwargs):
        self._call("copy", kwargs)
        with self.lock:
            source = kwargs["CopySource"]["Key"]
            data, mime, _version = self.objects[source]
            version = self.seed(kwargs["Key"], data, mime)
            return {"VersionId": version}


def uploaded_images(monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "post"
    store = EvidenceStore()
    monkeypatch.setattr(storage, "_client", lambda: store)
    # conftest's autouse fixture replaces these functions for legacy tests. Restore
    # their originals captured at collection, so real HEAD/GET/image decoding runs.
    monkeypatch.setattr(storage, "object_exists", real_object_exists)
    monkeypatch.setattr(storage, "validate_evidence_object", real_validate_evidence_object)
    return store


def photo(lab, store, kind, *, uploaded=True):
    factory = make_issue_evidence if kind == "issue" else make_return_evidence
    evidence = factory(lab.space, lab.actor)
    if uploaded:
        store.seed(storage.staging_key(evidence.object_key), png(), "image/png")
    return evidence


def domain_snapshot(lab):
    """Fixture preparation precedes snapshots; object promotion is not DB rollback."""
    models = (
        HardwareRequest, InventoryProduct, InventoryAsset, BoxScan, QrScanEvent,
        ReturnEvent, RequesterAccountability, EvidencePhoto,
    )
    result = {
        model.__name__: list(model.objects.filter(makerspace=lab.space).order_by("pk").values())
        for model in models
    }
    result["items"] = list(HardwareRequestItem.objects.filter(
        request__makerspace=lab.space,
    ).order_by("pk").values())
    result["links"] = list(HardwareRequestItemAsset.objects.filter(
        request_item__request__makerspace=lab.space,
    ).order_by("pk").values())
    # Avoid unrelated asynchronous/system audit rows; compare this tenant's domain events.
    result["audit"] = list(AuditLog.objects.filter(
        makerspace=lab.space, action__in=[
            "request.submitted", "request.accepted", "request.issued",
            "request.partially_returned", "request.returned", "evidence.attached",
            "box.assigned", "box.scanned", "asset.issued", "item.damaged", "item.missing",
        ],
    ).order_by("pk").values())
    # EvidenceUploadFinalization deliberately excluded: valid byte promotion may
    # precede a domain rejection and is durable independently of hardware changes.
    return result


def rejected(lab, url, payload, status=400, code=None):
    before = domain_snapshot(lab)
    response = lab.client.post(url, payload, format="json")
    assert response.status_code == status, response.data
    if code:
        assert response.data["code"] == code
    assert domain_snapshot(lab) == before


def assert_attachment(lab, loan, evidence, action):
    entry = AuditLog.objects.get(makerspace=lab.space, action=action, target_id=str(loan.pk))
    assert entry.actor_id == lab.actor.pk
    assert entry.meta["evidence_id"] == evidence.pk
    loan.refresh_from_db()
    assert entry.meta["box_id"] == loan.assigned_box_id
    attached = AuditLog.objects.get(
        makerspace=lab.space, action="evidence.attached", target_id=str(evidence.pk),
        meta__request_id=loan.pk,
    )
    assert attached.actor_id == lab.actor.pk
    finalized = EvidenceUploadFinalization.objects.get(evidence=evidence)
    assert finalized.status == "finalized"
    assert finalized.size_bytes == len(png()) and finalized.content_type == "image/png"


def retained_rows(lab):
    """Immutable metadata, scans, return events and audit must survive later stages."""
    models = (EvidencePhoto, BoxScan, QrScanEvent, ReturnEvent, AuditLog)
    return {
        model: {row["id"]: row for row in model.objects.filter(makerspace=lab.space).values()}
        for model in models
    }


def assert_retained(lab, before):
    after = retained_rows(lab)
    for model, rows in before.items():
        assert {pk: after[model][pk] for pk in rows} == rows
