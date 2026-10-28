import pytest
from django.test import override_settings

from apps.boxes.models import QrCode
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from tests.return_helpers import active_loans_url, make_issued_request
from tests.test_admin_direct_loans import (
    authed,
    direct_payload,
    direct_url,
    make_admin,
    make_product,
    make_space,
)

pytestmark = pytest.mark.django_db


def _box_out_on_reviewed_request(makerspace, admin, status=HardwareRequest.Status.ISSUED):
    product = make_product(makerspace, name="Reviewed tool")
    request = make_issued_request(makerspace, admin, [(product, 1)])
    if status != request.status:
        request.status = status
        request.save(update_fields=["status", "updated_at"])
    return request.assigned_box


@pytest.mark.parametrize(
    "status",
    [HardwareRequest.Status.ISSUED, HardwareRequest.Status.PARTIALLY_RETURNED],
)
@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_handout_refuses_container_issued_on_reviewed_request(status):
    makerspace = make_space(f"guard-container-{status}")
    admin = make_admin(makerspace)
    box = _box_out_on_reviewed_request(makerspace, admin, status)
    product = make_product(makerspace, name="Handout tool")

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(
            makerspace=makerspace,
            container_id=box.id,
            items=[{"product_id": product.id, "quantity": 1}],
        ),
        format="json",
    )

    assert response.status_code == 409
    assert response.data["detail"] == "That container is already out on an issued request."
    assert PublicToolLoan.objects.count() == 0
    product.refresh_from_db()
    assert product.available_quantity == 3


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_box_qr_checkout_refuses_box_issued_on_reviewed_request():
    makerspace = make_space("guard-box-qr")
    admin = make_admin(makerspace)
    box = _box_out_on_reviewed_request(makerspace, admin)
    boxed = make_product(makerspace, name="Boxed tool", box=box)
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.BOX,
        target_id=box.id,
    )

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(makerspace=makerspace, qr_payloads=[qr.payload]),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == "This box is already checked out."
    assert PublicToolLoan.objects.count() == 0
    boxed.refresh_from_db()
    assert boxed.available_quantity == 3


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_box_returned_on_reviewed_request_can_be_handed_out_again():
    makerspace = make_space("guard-box-returned")
    admin = make_admin(makerspace)
    box = _box_out_on_reviewed_request(makerspace, admin, HardwareRequest.Status.RETURNED)
    product = make_product(makerspace, name="Handout tool")

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(
            makerspace=makerspace,
            container_id=box.id,
            items=[{"product_id": product.id, "quantity": 1}],
        ),
        format="json",
    )

    assert response.status_code == 201
    assert PublicToolLoan.objects.get().container_id == box.id


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_active_loans_queue_lists_only_reviewed_request_loans():
    makerspace = make_space("guard-active-queue")
    admin = make_admin(makerspace)
    reviewed = make_issued_request(makerspace, admin, [(make_product(makerspace), 1)])
    client = authed(admin)
    handout = client.post(
        direct_url(makerspace),
        direct_payload(
            makerspace=makerspace,
            items=[{"product_id": make_product(makerspace, name="Handout").id, "quantity": 1}],
        ),
        format="json",
    )
    assert handout.status_code == 201
    assert HardwareRequest.objects.filter(status=HardwareRequest.Status.ISSUED).count() == 2

    response = client.get(active_loans_url(makerspace))

    assert response.status_code == 200
    assert [row["id"] for row in response.data["results"]] == [reviewed.id]
