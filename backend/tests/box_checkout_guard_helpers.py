"""Real checkout fixtures and complete rollback observations for HW002/BOX-S01."""
from types import SimpleNamespace

from django.conf import settings

from apps.audit.models import AuditLog
from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.evidence import storage
from apps.evidence.models import EvidencePhoto, EvidenceUploadFinalization
from apps.hardware_requests.models import (
    HardwareRequest, HardwareRequestItem, HardwareRequestItemAsset,
    PublicToolLoan, RequesterAccountability, ReturnEvent,
)
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace
from apps.operations.services_qr_assets import generate_assets_with_qr
from tests.atomic_publication.store import png
from tests.inventory_lending_evidence_helpers import uploaded_images
from tests.inventory_lending_helpers import make_lab
from tests.return_helpers import authenticated_client, make_issue_evidence, make_return_evidence
from tests.test_box_checkout_integrity import eligible_member


SEPARATE_CONTENTS = (
    "This box requires separate contents selection. Scan individual units "
    "using their own QR codes; for a staff handout, select the container "
    "and contents separately."
)


def checkout_lab(monkeypatch, settings, transport="post", *, individual=False):
    lab = make_lab(
        monkeypatch, settings,
        tracking_mode=TrackingMode.INDIVIDUAL if individual else TrackingMode.QUANTITY,
    )
    lab.store = uploaded_images(monkeypatch, settings)
    settings.STORAGE_PRESIGN_METHOD = transport
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    # Managed host admission remains real; the test client is an explicit infra host.
    settings.INFRA_HOSTS = {*settings.INFRA_HOSTS, "testserver"}
    # A finite managed cap makes PUT rollback and committed charges observable.
    lab.space.resource_limit_overrides = {"storage": 8 * len(png())}
    lab.space.save(update_fields=["resource_limit_overrides"])
    lab.product.public_self_checkout_enabled = True
    lab.product.save(update_fields=["public_self_checkout_enabled"])
    for asset in lab.assets:
        asset.public_self_checkout_enabled = True
        asset.save(update_fields=["public_self_checkout_enabled"])
    lab.borrower = eligible_member(lab.space)
    lab.public = authenticated_client(lab.borrower)
    lab.client.defaults["HTTP_HOST"] = "testserver"
    lab.public.defaults["HTTP_HOST"] = "testserver"
    lab.transport = transport
    return lab


def box_qr(lab, *, parent=None, label="Root kit", active=True):
    box = Box.objects.create(
        makerspace=lab.space, parent=parent, label=label, is_active=active,
    )
    qr = QrCode.objects.create(
        makerspace=lab.space, target_type="box", target_id=box.pk, payload=box.code,
    )
    return box, qr


def root_kit(lab):
    box, qr = box_qr(lab)
    lab.product.box = box
    lab.product.save(update_fields=["box"])
    return box, qr


def contained_unit(lab, box):
    product = InventoryProduct.objects.create(
        makerspace=lab.space, name="PRIVATE calibrated unit", box=box,
        tracking_mode=TrackingMode.INDIVIDUAL, total_quantity=0, available_quantity=0,
        is_public=True, public_self_checkout_enabled=True,
    )
    generated, _ = generate_assets_with_qr(lab.actor, product, {"count": 1})
    asset, qr = generated[0]["asset"], generated[0]["qr"]
    asset.public_self_checkout_enabled = True
    asset.save(update_fields=["public_self_checkout_enabled"])
    return SimpleNamespace(product=product, asset=asset, qr=qr)


def uploaded_photo(lab, surface, kind="issue"):
    actor = lab.borrower if surface == "public" else lab.actor
    factory = make_issue_evidence if kind == "issue" else make_return_evidence
    evidence = factory(lab.space, actor)
    lab.store.seed(storage.staging_key(evidence.object_key), png(), "image/png")
    return evidence


def checkout(lab, surface, qrs, evidence, *, container=None):
    body = {"qr_payloads": [qr.payload for qr in qrs], "evidence_id": evidence.pk}
    if surface == "public":
        assert container is None
        url = f"/api/v1/public/{lab.space.slug}/tools/checkout"
        client = lab.public
    else:
        body["borrower_id"] = lab.borrower.pk
        if container:
            body["container_id"] = container.pk
        url = f"/api/v1/admin/makerspace/{lab.space.pk}/direct-loans"
        client = lab.client
    return client.post(url, body, format="json")


def snapshot():
    """All tenants, all relevant rows; no audit-action allowlist hides side effects."""
    models = (
        InventoryProduct, InventoryAsset, HardwareRequest, HardwareRequestItem,
        HardwareRequestItemAsset, PublicToolLoan, BoxScan, QrScanEvent, AuditLog,
        EvidencePhoto, ReturnEvent, RequesterAccountability, QrCode,
    )
    result = {model.__name__: list(model.objects.order_by("pk").values()) for model in models}
    result["maker_storage"] = list(Makerspace.objects.order_by("pk").values_list(
        "pk", "storage_bytes_used",
    ))
    # Finalization is independent of attachment: valid bytes may be promoted before
    # a 400. Stock, evidence relationships and committed storage must still roll back.
    return result


def assert_png_promoted(lab, evidence, *, charged=False):
    state = EvidenceUploadFinalization.objects.get(evidence=evidence)
    assert (state.status, state.size_bytes, state.content_type, state.quota_charged) == (
        "finalized", len(png()), "image/png", charged,
    )
    assert lab.store.objects[evidence.object_key][:2] == (png(), "image/png")
    assert storage.staging_key(evidence.object_key) not in lab.store.objects
    # Real GET/image decoding must have occurred on both sides of promotion.
    read_keys = {args["Key"] for name, args in lab.store.calls if name == "get"}
    assert {storage.staging_key(evidence.object_key), evidence.object_key} <= read_keys
    assert all(
        args["Bucket"] == settings.AWS_STORAGE_BUCKET_NAME
        for name, args in lab.store.calls if name in {"get", "head", "copy"}
    )


def assert_refusal(lab, surface, qr, *, detail=SEPARATE_CONTENTS):
    evidence = uploaded_photo(lab, surface)
    before = snapshot()
    response = checkout(lab, surface, [qr], evidence)
    assert response.status_code == 400, response.data
    # An exact generic payload excludes hidden names, IDs, counts and unit details.
    assert response.data == {"detail": detail, "code": "validation_error"}
    assert snapshot() == before
    assert_png_promoted(lab, evidence)
    assert not HardwareRequest.objects.filter(issue_evidence=evidence).exists()
    return response


def resolve_actions(lab, qr):
    before = snapshot()
    response = lab.client.post(
        "/api/v1/admin/qr/resolve", {"payload": qr.payload}, format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["target"]["id"] == qr.target_id
    assert response.data["qr"]["id"] == qr.pk
    scans = QrScanEvent.objects.exclude(pk__in=[row["id"] for row in before["QrScanEvent"]])
    scan = scans.get()
    assert (scan.qr_code_id, scan.actor_id, scan.context, scan.request_id) == (
        qr.pk, lab.actor.pk, "scanner_lookup", None,
    )
    after = snapshot()
    audit_ids = {row["id"] for row in before["AuditLog"]}
    new_audits = [row for row in after["AuditLog"] if row["id"] not in audit_ids]
    assert len(new_audits) == 1
    audit = new_audits[0]
    assert qr.makerspace_id == lab.space.pk
    assert (
        audit["action"], audit["actor_id"], audit["makerspace_id"],
        audit["target_type"], audit["target_id"], audit["meta"],
    ) == (
        "qr.scanned", lab.actor.pk, qr.makerspace_id,
        "boxes.qrcode", str(qr.pk), {"context": scan.context, "scan_id": scan.pk},
    )
    assert scan.makerspace_id == qr.makerspace_id
    before["AuditLog"] = [*before["AuditLog"], audit]
    scan_row = next(row for row in after["QrScanEvent"] if row["id"] == scan.pk)
    before["QrScanEvent"] = [*before["QrScanEvent"], scan_row]
    assert after == before
    return set(response.data["allowed_actions"])


def assert_scanner_refusal(lab, qr):
    actions = resolve_actions(lab, qr)
    assert {"view", "contents"} <= actions
    assert actions.isdisjoint({"checkout", "direct_handout"})
