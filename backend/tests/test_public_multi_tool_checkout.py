import pytest
from django.test import override_settings

from apps.audit.models import AuditLog
from apps.boxes.models import QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from tests.test_public_self_checkout import (
    checkout_payload,
    checkout_url,
    eligible_member,
    make_product,
    make_qr,
    make_space,
    member_client,
    public_evidence,
    return_payload,
    return_url,
)

pytestmark = pytest.mark.django_db


def _batch_payload(makerspace, user, qrs):
    return {
        "qr_payloads": [qr.payload for qr in qrs],
        "evidence_id": public_evidence(
            makerspace, user, EvidencePhoto.EvidenceType.ISSUE
        ).id,
        "remark": "Checked out together.",
    }


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_two_separate_qrs_create_one_request_and_one_loan():
    makerspace = make_space("multi-checkout")
    user = eligible_member(makerspace, "multi-checkout-member")
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
    qrs = [make_qr(makerspace, product_a), make_qr(makerspace, product_b)]

    response = member_client(user).post(
        checkout_url(makerspace),
        _batch_payload(makerspace, user, qrs),
        format="json",
    )

    assert response.status_code == 201
    assert HardwareRequest.objects.count() == 1
    assert PublicToolLoan.objects.count() == 1
    loan = PublicToolLoan.objects.get()
    assert loan.qr_code == qrs[0]
    assert loan.qr_ids == [qr.id for qr in qrs]
    assert sorted(response.data["items"], key=lambda item: item["product_name"]) == [
        {"product_name": "Logic Analyzer", "quantity": 1},
        {"product_name": "Multimeter", "quantity": 1},
    ]
    assert list(
        QrScanEvent.objects.filter(context=QrScanEvent.Context.ISSUE)
        .order_by("qr_code_id")
        .values_list("qr_code_id", flat=True)
    ) == sorted(qr.id for qr in qrs)


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_returning_second_qr_resolves_entire_batch_loan():
    makerspace = make_space("multi-return")
    user = eligible_member(makerspace, "multi-return-member")
    products = [
        make_product(
            makerspace,
            name=name,
            public_self_checkout_enabled=True,
        )
        for name in ("Clamp Meter", "Soldering Iron")
    ]
    qrs = [make_qr(makerspace, product) for product in products]
    client = member_client(user)
    checkout = client.post(
        checkout_url(makerspace),
        _batch_payload(makerspace, user, qrs),
        format="json",
    )
    assert checkout.status_code == 201

    response = client.post(
        return_url(makerspace),
        return_payload(makerspace, user, qrs[1].payload),
        format="json",
    )

    assert response.status_code == 200
    loan = PublicToolLoan.objects.get()
    assert loan.status == PublicToolLoan.Status.RETURNED
    assert loan.request.status == HardwareRequest.Status.RETURNED
    for product in products:
        product.refresh_from_db()
        assert product.available_quantity == 2
        assert product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_batch_with_active_qr_is_refused_without_partial_writes():
    makerspace = make_space("multi-active-refusal")
    user = eligible_member(makerspace, "multi-active-refusal-member")
    active_product = make_product(
        makerspace,
        name="Already Out",
        public_self_checkout_enabled=True,
    )
    fresh_product = make_product(
        makerspace,
        name="Still Available",
        public_self_checkout_enabled=True,
    )
    active_qr = make_qr(makerspace, active_product)
    fresh_qr = make_qr(makerspace, fresh_product)
    client = member_client(user)
    first = client.post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, active_qr.payload),
        format="json",
    )
    assert first.status_code == 201
    baseline = {
        "requests": HardwareRequest.objects.count(),
        "loans": PublicToolLoan.objects.count(),
        "scans": QrScanEvent.objects.count(),
        "audits": AuditLog.objects.count(),
    }
    batch = _batch_payload(makerspace, user, [fresh_qr, active_qr])

    response = client.post(checkout_url(makerspace), batch, format="json")

    assert response.status_code == 409
    assert response.data["detail"] == "This QR code is already checked out."
    assert HardwareRequest.objects.count() == baseline["requests"]
    assert PublicToolLoan.objects.count() == baseline["loans"]
    assert QrScanEvent.objects.count() == baseline["scans"]
    assert AuditLog.objects.count() == baseline["audits"]
    assert not HardwareRequest.objects.filter(issue_evidence_id=batch["evidence_id"]).exists()
    fresh_product.refresh_from_db()
    assert fresh_product.available_quantity == 2
    assert fresh_product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_legacy_single_payload_checkout_shape_is_unchanged():
    makerspace = make_space("legacy-single-checkout")
    user = eligible_member(makerspace, "legacy-single-checkout-member")
    product = make_product(
        makerspace,
        name="Legacy Tool",
        public_self_checkout_enabled=True,
    )
    qr = make_qr(makerspace, product)

    response = member_client(user).post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload, remark="Legacy checkout."),
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == PublicToolLoan.Status.CHECKED_OUT
    assert response.data["items"] == [{"product_name": "Legacy Tool", "quantity": 1}]
    loan = PublicToolLoan.objects.get()
    assert loan.qr_code == qr
    assert loan.qr_ids == [qr.id]
    assert loan.target_type == qr.target_type
    assert loan.target_id == qr.target_id
    assert loan.target_label == product.name
    assert loan.request.issue_remark == "Legacy checkout."
    assert QrScanEvent.objects.filter(
        qr_code=qr,
        context=QrScanEvent.Context.ISSUE,
        request=loan.request,
    ).count() == 1
