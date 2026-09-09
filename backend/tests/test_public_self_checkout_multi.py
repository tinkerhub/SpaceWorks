import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.boxes.models import QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.presence import services as presence

pytestmark = pytest.mark.django_db


def make_space(slug="self-checkout-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_product(makerspace, **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": "USB Logic Analyzer",
        "total_quantity": 2,
        "available_quantity": 2,
        "is_public": True,
        "is_archived": False,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


def make_qr(makerspace, product):
    return QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.id,
    )


def eligible_member(makerspace, username="member-1"):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        phone="+15550101010",
        display_name="Self Checkout",
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="member"),
    )
    presence.start_session(user, makerspace, 60)
    return user


def member_client(user):
    client = APIClient(REMOTE_ADDR="10.20.30.40")
    client.force_authenticate(user)
    return client


def checkout_url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/tools/checkout"


def return_url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/tools/return"


def checkout_payload(makerspace, user, payload, **overrides):
    body = {
        "payload": payload,
    }
    body.update(overrides)
    if "evidence_id" not in body:
        body["evidence_id"] = public_evidence(
            makerspace, user, EvidencePhoto.EvidenceType.ISSUE
        ).id
    return body


def return_payload(
    makerspace, user, payload, remark="Returned in good condition.", **overrides
):
    body = {
        "payload": payload,
        "remark": remark,
        "evidence_id": public_evidence(
            makerspace, user, EvidencePhoto.EvidenceType.RETURN
        ).id,
    }
    body.update(overrides)
    return body


def public_evidence(makerspace, user, evidence_type):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=evidence_type,
        object_key=f"evidence/{makerspace.id}/{evidence_type}/{user.id}-{EvidencePhoto.objects.count() + 1}",
        uploaded_by=user,
    )


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_two_separately_tagged_qrs_checkout_as_one_public_loan():
    makerspace = make_space("multi-checkout")
    user = eligible_member(makerspace)
    product_a = make_product(
        makerspace,
        name="Logic Analyzer",
        public_self_checkout_enabled=True,
    )
    product_b = make_product(
        makerspace,
        name="Multimeter",
        public_self_checkout_enabled=True,
    )
    qr_a = make_qr(makerspace, product_a)
    qr_b = make_qr(makerspace, product_b)
    evidence = public_evidence(
        makerspace, user, EvidencePhoto.EvidenceType.ISSUE
    )

    response = member_client(user).post(
        checkout_url(makerspace),
        {
            "qr_payloads": [qr_a.payload, qr_b.payload],
            "evidence_id": evidence.id,
        },
        format="json",
    )

    assert response.status_code == 201
    assert HardwareRequest.objects.count() == 1
    assert PublicToolLoan.objects.count() == 1
    assert EvidencePhoto.objects.filter(
        evidence_type=EvidencePhoto.EvidenceType.ISSUE
    ).count() == 1
    request = HardwareRequest.objects.get()
    assert request.issue_evidence == evidence
    loan = PublicToolLoan.objects.get()
    assert loan.request == request
    assert loan.qr_code == qr_a
    assert loan.qr_ids == [qr_a.id, qr_b.id]
    assert list(
        QrScanEvent.objects.filter(context=QrScanEvent.Context.ISSUE)
        .order_by("qr_code_id")
        .values_list("qr_code_id", flat=True)
    ) == sorted([qr_a.id, qr_b.id])


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_returning_by_second_qr_closes_the_same_public_loan():
    makerspace = make_space("multi-return")
    user = eligible_member(makerspace)
    product_a = make_product(
        makerspace,
        name="Clamp Meter",
        public_self_checkout_enabled=True,
    )
    product_b = make_product(
        makerspace,
        name="Soldering Iron",
        public_self_checkout_enabled=True,
    )
    qr_a = make_qr(makerspace, product_a)
    qr_b = make_qr(makerspace, product_b)
    client = member_client(user)

    checkout = client.post(
        checkout_url(makerspace),
        {
            "qr_payloads": [qr_a.payload, qr_b.payload],
            "evidence_id": public_evidence(
                makerspace, user, EvidencePhoto.EvidenceType.ISSUE
            ).id,
        },
        format="json",
    )

    assert checkout.status_code == 201
    loan = PublicToolLoan.objects.get()

    returned = client.post(
        return_url(makerspace),
        return_payload(makerspace, user, qr_b.payload),
        format="json",
    )

    assert returned.status_code == 200
    assert returned.data["status"] == PublicToolLoan.Status.RETURNED
    loan.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.RETURNED
    assert PublicToolLoan.objects.get() == loan
    loan.request.refresh_from_db()
    assert loan.request.status == HardwareRequest.Status.RETURNED


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_batch_with_already_checked_out_qr_is_atomic():
    makerspace = make_space("multi-atomic")
    user = eligible_member(makerspace)
    checked_out_product = make_product(
        makerspace,
        name="Already Checked Out",
        public_self_checkout_enabled=True,
    )
    available_product = make_product(
        makerspace,
        name="Available Tool",
        public_self_checkout_enabled=True,
    )
    checked_out_qr = make_qr(makerspace, checked_out_product)
    available_qr = make_qr(makerspace, available_product)
    client = member_client(user)
    first_checkout = client.post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, checked_out_qr.payload),
        format="json",
    )

    assert first_checkout.status_code == 201
    request_count = HardwareRequest.objects.count()
    loan_count = PublicToolLoan.objects.count()
    scan_count = QrScanEvent.objects.count()

    response = client.post(
        checkout_url(makerspace),
        {
            "qr_payloads": [available_qr.payload, checked_out_qr.payload],
            "evidence_id": public_evidence(
                makerspace, user, EvidencePhoto.EvidenceType.ISSUE
            ).id,
        },
        format="json",
    )

    assert response.status_code == 409
    assert response.data["detail"] == "This QR code is already checked out."
    assert HardwareRequest.objects.count() == request_count
    assert PublicToolLoan.objects.count() == loan_count
    assert QrScanEvent.objects.count() == scan_count
    available_product.refresh_from_db()
    assert available_product.available_quantity == 2
    assert available_product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_original_single_payload_checkout_still_issues_one_request():
    makerspace = make_space("single-checkout")
    user = eligible_member(makerspace)
    product = make_product(
        makerspace,
        public_self_checkout_enabled=True,
    )
    qr = make_qr(makerspace, product)

    response = member_client(user).post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == PublicToolLoan.Status.CHECKED_OUT
    assert PublicToolLoan.objects.count() == 1
    loan = PublicToolLoan.objects.get()
    assert loan.qr_code == qr
    assert HardwareRequest.objects.count() == 1
    assert loan.request.status == HardwareRequest.Status.ISSUED
