import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.boxes.models import Box, QrCode
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.inventory.models import InventoryAsset, TrackingMode
from tests.test_box_checkout_integrity import (
    _evidence,
    direct_payload,
    direct_url,
    eligible_member,
    make_admin,
    make_box_qr,
    make_product,
    make_space,
    member_client,
    public_checkout_url,
)

pytestmark = pytest.mark.django_db

OVERLAP_MESSAGE = (
    "A scanned tool is inside a scanned box; scan either the box or the tool, not both."
)


def make_asset_qr(makerspace, asset):
    return QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id=asset.id,
    )


def make_asset(makerspace, product, asset_tag, *, box=None):
    return InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        box=box,
        asset_tag=asset_tag,
        public_self_checkout_enabled=True,
    )


def post_checkout(workflow, makerspace, borrower, qrs):
    if workflow == "public":
        return member_client(borrower).post(
            public_checkout_url(makerspace),
            {
                "qr_payloads": [qr.payload for qr in qrs],
                "evidence_id": _evidence(
                    makerspace, borrower, EvidencePhoto.EvidenceType.ISSUE
                ).id,
            },
            format="json",
        )

    client = APIClient()
    client.force_authenticate(make_admin(makerspace))
    return client.post(
        direct_url(makerspace),
        direct_payload(
            makerspace,
            borrower,
            qr_payloads=[qr.payload for qr in qrs],
        ),
        format="json",
    )


@pytest.mark.parametrize("workflow", ["public", "direct"])
@pytest.mark.parametrize("reverse_order", [False, True])
@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_box_and_contained_asset_qrs_are_rejected_before_issuance(
    workflow, reverse_order
):
    order = "asset-first" if reverse_order else "box-first"
    makerspace = make_space(f"overlap-{workflow}-{order}")
    borrower = eligible_member(makerspace, f"borrower-{workflow}-{order}")
    box = Box.objects.create(makerspace=makerspace, label="Calibration Kit")
    product = make_product(
        makerspace,
        name="Serialized Meter",
        box=box,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    asset = make_asset(makerspace, product, "METER-1", box=box)
    qrs = [make_box_qr(makerspace, box), make_asset_qr(makerspace, asset)]
    if reverse_order:
        qrs.reverse()

    response = post_checkout(workflow, makerspace, borrower, qrs)

    assert response.status_code == 409
    assert response.data["detail"] == OVERLAP_MESSAGE
    assert not HardwareRequest.objects.exists()
    assert not PublicToolLoan.objects.exists()
    asset.refresh_from_db()
    product.refresh_from_db()
    assert asset.status == InventoryAsset.Status.AVAILABLE
    assert product.available_quantity == 1
    assert product.issued_quantity == 0


@pytest.mark.parametrize("workflow", ["public", "direct"])
@pytest.mark.parametrize(
    "combination",
    ["independent-assets", "single-box", "box-and-uncontained-asset"],
)
@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_non_overlapping_qr_combinations_still_succeed(workflow, combination):
    makerspace = make_space(f"allowed-{workflow}-{combination}")
    borrower = eligible_member(makerspace, f"borrower-{workflow}-{combination}")

    if combination == "independent-assets":
        product = make_product(
            makerspace,
            name="Serialized Probes",
            tracking_mode=TrackingMode.INDIVIDUAL,
            total_quantity=2,
            available_quantity=2,
        )
        assets = [
            make_asset(makerspace, product, "PROBE-1"),
            make_asset(makerspace, product, "PROBE-2"),
        ]
        qrs = [make_asset_qr(makerspace, asset) for asset in assets]
        expected_container = None
    else:
        box = Box.objects.create(makerspace=makerspace, label="Cable Box")
        make_product(makerspace, name="Cable Set", box=box)
        qrs = [make_box_qr(makerspace, box)]
        assets = []
        expected_container = box
        if combination == "box-and-uncontained-asset":
            product = make_product(
                makerspace,
                name="Loose Meter",
                tracking_mode=TrackingMode.INDIVIDUAL,
                total_quantity=1,
                available_quantity=1,
            )
            asset = make_asset(makerspace, product, "LOOSE-METER-1")
            assets.append(asset)
            qrs.append(make_asset_qr(makerspace, asset))

    response = post_checkout(workflow, makerspace, borrower, qrs)

    assert response.status_code == 201
    loan = PublicToolLoan.objects.get()
    assert loan.container == expected_container
    assert sorted(loan.asset_ids) == sorted(asset.id for asset in assets)
    for asset in assets:
        asset.refresh_from_db()
        assert asset.status == InventoryAsset.Status.ISSUED
