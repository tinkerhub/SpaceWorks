"""Cancellation fixtures reserve through the real review API before testing release."""
from types import SimpleNamespace

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import (
    HardwareRequest, HardwareRequestItem, HardwareRequestItemAsset, PublicToolLoan,
    RequesterAccountability, ReturnEvent,
)
from apps.inventory.models import InventoryAsset, InventoryProduct
from tests.handout_roles import make_handout_member
from tests.test_request_workflow import (
    accept_url, authenticated_client, make_hardware_request, make_member,
    make_product, make_space,
)


def cancel_url(request):
    return f"/api/v1/admin/requests/{request.pk}/cancel"


def cancel(lab, **kwargs):
    return lab.client.post(cancel_url(lab.request),
                           {"reason": "Borrower changed their plans."}, format="json", **kwargs)


def accept(client, request, accepted=None):
    body = {} if accepted is None else {"accepted_quantities": [
        {"item_id": item_id, "quantity": quantity} for item_id, quantity in accepted.items()
    ]}
    response = client.post(accept_url(request), body, format="json")
    assert response.status_code == 200, response.content
    request.refresh_from_db()
    return request


def accepted_lab(*, quantity=2, tracking="quantity", physical_reserved=0, lines=None):
    space = make_space("cancel-home")
    actor = make_member("cancel-manager", space)
    product = make_product(space, total_quantity=8, available_quantity=8,
                           tracking_mode=tracking)
    assets = []
    if tracking == "individual":
        assets = [InventoryAsset.objects.create(
            makerspace=space, product=product, asset_tag=f"cancel-unit-{index}",
            status="reserved" if index < physical_reserved else "available",
        ) for index in range(8)]
        product.available_quantity = 8 - physical_reserved
        product.reserved_quantity = physical_reserved
        product.save(update_fields=["available_quantity", "reserved_quantity"])
    client = authenticated_client(actor)
    request = make_hardware_request(space, product, quantity=quantity)
    accepted = None
    if lines:
        first = request.items.get()
        first.requested_quantity = lines[0][0]
        first.save(update_fields=["requested_quantity"])
        accepted = {first.pk: lines[0][1]}
        for requested, approved in lines[1:]:
            item = HardwareRequestItem.objects.create(request=request, product=product,
                                                       requested_quantity=requested)
            accepted[item.pk] = approved
    accept(client, request, accepted)
    return SimpleNamespace(space=space, actor=actor, product=product, request=request,
                           client=client, assets=assets)


def reviewer(space, username="cancel-reviewer", actions=(rbac.Action.REJECT_REQUEST,)):
    return make_handout_member(username, space, slug=username, actions=actions)


def buckets(product):
    product.refresh_from_db()
    return (product.available_quantity, product.reserved_quantity,
            product.issued_quantity, product.total_quantity)


def assignment(lab, box=None):
    box = box or Box.objects.create(makerspace=lab.space, label="cancel-box")
    response = lab.client.post(f"/api/v1/admin/requests/{lab.request.pk}/assign-box",
                               {"box_code": box.code}, format="json")
    assert response.status_code == 200, response.content
    qr = QrCode.objects.create(makerspace=lab.space, target_type="box", target_id=box.pk)
    QrScanEvent.objects.create(makerspace=lab.space, qr_code=qr, request=lab.request,
                              actor=lab.actor, context="issue")
    lab.request.refresh_from_db()
    return box


def photo(lab, kind="issue"):
    return EvidencePhoto.objects.create(
        makerspace=lab.space, uploaded_by=lab.actor, evidence_type=kind,
        object_key=f"cancel/{kind}/{lab.request.pk}", content_type="image/png",
    )


def snapshot():
    """Exact durable rows, including immutable history and all stock buckets."""
    models = (HardwareRequest, HardwareRequestItem, HardwareRequestItemAsset,
              PublicToolLoan, RequesterAccountability, ReturnEvent, InventoryProduct,
              InventoryAsset, Box, BoxScan, QrScanEvent, EvidencePhoto, AuditLog)
    return {model._meta.label: list(model.objects.order_by("pk").values()) for model in models}


def refused(lab, status=409, client=None, **headers):
    before = snapshot()
    response = (client or lab.client).post(cancel_url(lab.request),
        {"reason": "Must never be persisted on refusal."}, format="json", **headers)
    assert response.status_code in (status if isinstance(status, tuple) else (status,)), response.content
    assert snapshot() == before
    return response
