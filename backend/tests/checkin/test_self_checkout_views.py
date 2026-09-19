"""Checked-in walk-ins can own public self-checkout evidence and loans."""

from datetime import datetime, timedelta, timezone

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.boxes.models import QrCode, QrScanEvent
from apps.checkin.client import CheckinEntry
from apps.checkin.models import CheckinIdentity
from apps.checkin.throttles import CheckinMidThrottle
from apps.evidence.models import EvidencePhoto
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests.models import PublicToolLoan
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.request_access import MODE_CHECKED_IN


pytestmark = pytest.mark.django_db


def _space(slug):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=[],
        enabled_features=["inventory.self_checkout"],
        public_request_mode=MODE_CHECKED_IN,
        checkin_space_id=1,
    )


def _entry(mid=443, name="Ada Example"):
    now = datetime.now(timezone.utc)
    return CheckinEntry(
        mid=mid,
        name=name,
        avatar="",
        purpose="Working on a project",
        project_name="Metrocard",
        check_in_time=now - timedelta(hours=1),
        check_out_time=now + timedelta(hours=1),
        space_id=1,
    )


def _tool(space):
    product = InventoryProduct.objects.create(
        makerspace=space,
        name="USB Logic Analyzer",
        total_quantity=1,
        available_quantity=1,
        is_public=True,
        public_self_checkout_enabled=True,
    )
    qr = QrCode.objects.create(
        makerspace=space,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.pk,
    )
    return product, qr


def _identity_payload(mid, name, **values):
    return {"checkin_mid": mid, "name": name, **values}


def _evidence(client, space, mid, name, evidence_type):
    return client.post(
        reverse("hardware_requests:public-tool-evidence-url", args=[space.slug]),
        _identity_payload(
            mid,
            name,
            evidence_type=evidence_type,
            content_type="image/png",
        ),
        format="json",
    )


def _stub_storage(monkeypatch):
    monkeypatch.setattr(
        "apps.hardware_requests.self_checkout_views.presigned_upload",
        lambda object_key, content_type: {
            "url": "https://storage.test/upload",
            "fields": {"key": object_key},
        },
    )
    monkeypatch.setattr(
        "apps.evidence.storage.finalize_upload",
        lambda evidence, max_bytes: EvidenceValidationResult(
            size=123, content_type="image/png"
        ),
    )


@pytest.mark.parametrize(
    "view_name",
    [
        "hardware_requests:public-tool-evidence-url",
        "hardware_requests:public-tool-checkout",
        "hardware_requests:public-tool-return",
    ],
)
@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_non_checkin_policies_keep_the_unauthenticated_401(view_name):
    space = Makerspace.objects.create(
        name=f"{view_name}-auth",
        slug=view_name.rsplit(":", 1)[-1],
        enabled_modules=[],
        enabled_features=["inventory.self_checkout"],
    )

    response = APIClient().post(
        reverse(view_name, args=[space.slug]), {}, format="json"
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication credentials were not provided."
    }


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_checked_in_walk_in_can_check_out_and_return(monkeypatch):
    space = _space("checkin-self-checkout")
    product, qr = _tool(space)
    client = APIClient(REMOTE_ADDR="10.20.30.40")
    order = []

    def allow_mid_request(throttle, request, view):
        order.append(("throttle", request.checkin_mid, request.checkin_makerspace_id))
        return True

    def fetch_roster(*, cached):
        order.append(("upstream", cached))
        return [_entry()]

    monkeypatch.setattr(CheckinMidThrottle, "allow_request", allow_mid_request)
    monkeypatch.setattr("apps.checkin.client.fetch_roster", fetch_roster)
    _stub_storage(monkeypatch)

    issue_upload = _evidence(
        client, space, 443, "ada   example", EvidencePhoto.EvidenceType.ISSUE
    )
    assert issue_upload.status_code == 201, issue_upload.content

    checkout = client.post(
        reverse("hardware_requests:public-tool-checkout", args=[space.slug]),
        _identity_payload(
            443,
            "Ada Example",
            payload=qr.payload,
            evidence_id=issue_upload.data["evidence_id"],
        ),
        format="json",
    )
    assert checkout.status_code == 201, checkout.content

    return_upload = _evidence(
        client, space, 443, "Ada Example", EvidencePhoto.EvidenceType.RETURN
    )
    assert return_upload.status_code == 201, return_upload.content
    returned = client.post(
        reverse("hardware_requests:public-tool-return", args=[space.slug]),
        _identity_payload(
            443,
            "Ada Example",
            payload=qr.payload,
            evidence_id=return_upload.data["evidence_id"],
            remark="Returned in good condition.",
        ),
        format="json",
    )

    assert returned.status_code == 200, returned.content
    identity = CheckinIdentity.objects.get(makerspace=space)
    loan = PublicToolLoan.objects.get(makerspace=space)
    assert loan.requester_id == identity.user_id
    assert loan.request.issue_evidence.uploaded_by_id == identity.user_id
    assert loan.return_evidence.uploaded_by_id == identity.user_id
    assert loan.status == PublicToolLoan.Status.RETURNED
    assert not MakerspaceMembership.objects.filter(user_id=identity.user_id).exists()
    product.refresh_from_db()
    assert product.available_quantity == 1
    assert product.issued_quantity == 0
    assert order == [
        ("throttle", 443, space.pk),
        ("upstream", False),
    ] * 4


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_different_checked_in_person_cannot_return_the_first_persons_tool(monkeypatch):
    space = _space("checkin-self-return-owner")
    _, qr = _tool(space)
    client = APIClient(REMOTE_ADDR="10.20.30.41")
    monkeypatch.setattr(
        "apps.checkin.client.fetch_roster",
        lambda *, cached: [_entry(), _entry(mid=884, name="Bee Sample")],
    )
    _stub_storage(monkeypatch)

    issue_upload = _evidence(
        client, space, 443, "Ada Example", EvidencePhoto.EvidenceType.ISSUE
    )
    checkout = client.post(
        reverse("hardware_requests:public-tool-checkout", args=[space.slug]),
        _identity_payload(
            443,
            "Ada Example",
            payload=qr.payload,
            evidence_id=issue_upload.data["evidence_id"],
        ),
        format="json",
    )
    assert checkout.status_code == 201, checkout.content

    return_upload = _evidence(
        client, space, 884, "Bee Sample", EvidencePhoto.EvidenceType.RETURN
    )
    response = client.post(
        reverse("hardware_requests:public-tool-return", args=[space.slug]),
        _identity_payload(
            884,
            "Bee Sample",
            payload=qr.payload,
            evidence_id=return_upload.data["evidence_id"],
            remark="Trying another person's return.",
        ),
        format="json",
    )

    assert response.status_code == 403
    assert response.data["code"] == "requester_blocked"
    identities = {
        identity.mid: identity
        for identity in CheckinIdentity.objects.select_related("user").filter(
            makerspace=space
        )
    }
    loan = PublicToolLoan.objects.get(makerspace=space)
    assert loan.requester_id == identities["443"].user_id
    assert loan.requester_id != identities["884"].user_id
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT
    assert loan.return_evidence_id is None
    assert not QrScanEvent.objects.filter(context=QrScanEvent.Context.RETURN).exists()
