import importlib

import pytest
from django.apps import apps
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.boxes.models import Box, QrCode
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.presence import services as presence

pytestmark = pytest.mark.django_db

def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_admin(makerspace):
    user = User.objects.create_user(
        username=f"admin-{makerspace.slug}",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return user


def eligible_member(makerspace, username="box-member"):
    user = User.objects.create_user(
        username=f"{username}-{makerspace.slug}",
        email=f"{username}-{makerspace.slug}@example.com",
        phone="+15550101010",
        display_name="Box Borrower",
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
    client = APIClient()
    client.force_authenticate(user)
    return client


def make_product(makerspace, **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": "Loan Item",
        "total_quantity": 2,
        "available_quantity": 2,
        "is_public": True,
        "public_self_checkout_enabled": True,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


def make_box_qr(makerspace, box):
    return QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.BOX,
        target_id=box.id,
    )


def checkout_payload(makerspace, member, payload):
    return {
        "payload": payload,
        "evidence_id": _evidence(makerspace, member, EvidencePhoto.EvidenceType.ISSUE).id,
    }

def public_checkout_url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/tools/checkout"


def direct_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/direct-loans"


def direct_payload(makerspace, borrower, **overrides):
    payload = {
        "borrower_id": borrower.id,
        "evidence_id": _evidence(makerspace, borrower, EvidencePhoto.EvidenceType.ISSUE).id,
    }
    payload.update(overrides)
    return payload


def _evidence(makerspace, user, evidence_type):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=evidence_type,
        object_key=f"evidence/{makerspace.id}/{evidence_type}/{user.id}-{EvidencePhoto.objects.count() + 1}",
        uploaded_by=user,
    )

@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_box_checkout_refuses_mixed_asset_and_quantity_contents(monkeypatch, settings):
    from types import SimpleNamespace

    from apps.operations.services_qr_assets import generate_assets_with_qr
    from tests.box_checkout_guard_helpers import assert_refusal
    from tests.inventory_lending_evidence_helpers import uploaded_images

    makerspace = make_space("box-mixed-public")
    member = eligible_member(makerspace)
    admin = make_admin(makerspace)
    box = Box.objects.create(makerspace=makerspace, label="Mixed Box")
    individual_product = make_product(
        makerspace,
        name="Serialized Meter",
        box=box,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=0,
        available_quantity=0,
    )
    generated, _ = generate_assets_with_qr(admin, individual_product, {"count": 1})
    asset = generated[0]["asset"]
    asset.public_self_checkout_enabled = True
    asset.save(update_fields=["public_self_checkout_enabled"])
    make_product(makerspace, name="Cable Kit", box=box)
    qr = make_box_qr(makerspace, box)
    lab = SimpleNamespace(
        space=makerspace, actor=admin, borrower=member, public=member_client(member),
        store=uploaded_images(monkeypatch, settings),
    )

    assert_refusal(lab, "public", qr)


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_box_checkout_blocks_subsequent_direct_container_loan():
    makerspace = make_space("box-public-blocks-direct")
    member = eligible_member(makerspace)
    box = Box.objects.create(makerspace=makerspace, label="Shared Box")
    make_product(makerspace, name="Shared Kit", box=box)
    qr = make_box_qr(makerspace, box)
    member_client(member).post(
        public_checkout_url(makerspace), checkout_payload(makerspace, member, qr.payload), format="json"
    )
    admin = make_admin(makerspace)
    borrower = eligible_member(makerspace, "direct-box")
    client = APIClient()
    client.force_authenticate(admin)

    response = client.post(
        direct_url(makerspace),
        direct_payload(makerspace, borrower, container_id=box.id, items=[]),
        format="json",
    )

    assert response.status_code == 409
    assert PublicToolLoan.objects.filter(container=box, status="checked_out").count() == 1


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_box_qr_loan_sets_container():
    makerspace = make_space("box-direct-qr")
    box = Box.objects.create(makerspace=makerspace, label="Direct QR Box")
    product = make_product(makerspace, name="Direct Box Kit", box=box)
    qr = make_box_qr(makerspace, box)
    admin = make_admin(makerspace)
    borrower = eligible_member(makerspace, "direct-box")
    client = APIClient()
    client.force_authenticate(admin)

    response = client.post(
        direct_url(makerspace),
        direct_payload(makerspace, borrower, qr_payloads=[qr.payload]),
        format="json",
    )

    assert response.status_code == 201
    loan = PublicToolLoan.objects.get()
    assert loan.container == box
    assert loan.qr_code == qr
    product.refresh_from_db()
    assert product.available_quantity == 1
    assert product.issued_quantity == 1


def test_box_loan_container_backfill_migration_sets_matching_box():
    makerspace = make_space("box-backfill")
    requester = User.objects.create_user(
        username="box-backfill-user",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    box = Box.objects.create(makerspace=makerspace, label="Backfill Box")
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username="box-backfill-user",
        status=HardwareRequest.Status.ISSUED,
    )
    loan = PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=request,
        requester=requester,
        target_type="box",
        target_id=box.id,
        target_label=box.label,
    )
    migration = importlib.import_module(
        "apps.hardware_requests.migrations.0019_backfill_box_loan_containers"
    )

    migration.backfill_box_loan_containers(apps, None)

    loan.refresh_from_db()
    assert loan.container == box





def test_assign_box_rejects_box_with_active_public_container_loan():
    from apps.hardware_requests.handover_workflow import assign_box
    from apps.hardware_requests.workflow_errors import BoxUnavailable

    makerspace = make_space("box-public-blocks-request-assign")
    admin = make_admin(makerspace)
    requester = User.objects.create_user(
        username="box-public-blocks-requester",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    box = Box.objects.create(makerspace=makerspace, label="Already Out")
    public_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ISSUED,
    )
    PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=public_request,
        requester=requester,
        container=box,
        target_type="box",
        target_id=box.id,
        target_label=box.label,
    )
    target_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ACCEPTED,
    )

    with pytest.raises(BoxUnavailable, match="already out"):
        assign_box(admin, target_request, box.code)

    target_request.refresh_from_db()
    assert target_request.assigned_box_id is None
