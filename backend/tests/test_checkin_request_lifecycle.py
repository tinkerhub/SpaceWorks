"""A check-in borrower's request and print job, through the whole staff lifecycle.

`tests/checkin/` proves the gate (lookup, submit, refusals). This proves what comes after on
the production configuration -- check-in mode, `membership`, `member_accounts` and
`payments` off: the account-less requester the roster minted can be accepted, handed a box,
issued with evidence and returned, and a machine job for one completes and is collected
without any payment being raised. Only the upstream roster is replaced.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.checkin.client import CheckinEntry
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests.models import HardwareRequest
from apps.machines.models import Machine, MachineServiceRequest, MachineType
from apps.makerspaces.request_access import MODE_CHECKED_IN
from apps.payments.models import Payment
from tests.return_helpers import (
    make_box,
    make_issue_evidence,
    make_member,
    make_product,
    make_return_evidence,
    make_space,
)

pytestmark = pytest.mark.django_db

PROD_LIKE = [
    "public_inventory", "request_workflow", "staff_admin", "scanner", "evidence_uploads",
    "qr_management", "guest_handover", "containers", "machines", "machine_service",
]


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _uploaded(monkeypatch):
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    monkeypatch.setattr(
        "apps.evidence.storage.finalize_upload",
        Mock(side_effect=lambda evidence, max_bytes: EvidenceValidationResult(size=321, content_type="image/jpeg")),
    )


def _space(slug):
    space = make_space(slug)
    space.enabled_modules = list(PROD_LIKE)
    space.public_request_mode = MODE_CHECKED_IN
    space.checkin_space_id = 1
    space.save()
    return space


def _roster(mid=4401, name="Asha Menon"):
    now = datetime.now(timezone.utc)
    entry = CheckinEntry(
        mid=mid, name=name, avatar="", purpose="Working on a project", project_name="Line follower",
        check_in_time=now - timedelta(hours=1), check_out_time=None, space_id=1,
    )
    return patch("apps.checkin.client.fetch_roster", return_value=[entry])


def _staff(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_checkin_borrow_request_runs_accept_issue_return():
    space = _space("checkin-lifecycle")
    manager = make_member("checkin-lifecycle-manager", space)
    product = make_product(space, name="Soldering Station", total_quantity=3, available_quantity=3)
    box = make_box(space, "Desk bin")

    with _roster():
        submitted = APIClient().post(
            reverse("hardware_requests:request-submit", args=[space.slug]),
            {"checkin_mid": 4401, "name": "asha  menon", "requested_for": "Soldering",
             "items": [{"product_id": product.id, "quantity": 2}]},
            format="json", HTTP_IDEMPOTENCY_KEY="lifecycle-1",
        )
    assert submitted.status_code == 201, submitted.data
    request = HardwareRequest.objects.get()
    # The canonical roster name, not the caller's spelling, is what staff review.
    assert request.requester_name == "Asha Menon"

    staff = _staff(manager)
    pending = staff.get(f"/api/v1/admin/makerspace/{space.id}/pending-requests")
    row = pending.data["results"][0]
    assert row["checkin_project_name"] == "Line follower"
    item_id = row["items"][0]["id"]

    accepted = staff.post(f"/api/v1/admin/requests/{request.id}/accept",
                          {"accepted_quantities": [{"item_id": item_id, "quantity": 2}]}, format="json")
    assigned = staff.post(f"/api/v1/admin/requests/{request.id}/assign-box", {"box_code": box.code}, format="json")
    issued = staff.post(f"/api/v1/admin/requests/{request.id}/issue",
                        {"evidence_id": make_issue_evidence(space, manager).id, "remark": "Handed over"}, format="json")
    assert (accepted.status_code, assigned.status_code, issued.status_code) == (200, 200, 200), (
        accepted.data, assigned.data, issued.data)
    product.refresh_from_db()
    assert (product.available_quantity, product.issued_quantity) == (1, 2)

    returned = staff.post(f"/api/v1/admin/requests/{request.id}/return", {
        "evidence_id": make_return_evidence(space, manager).id, "box_code": box.code,
        "remark": "Both back, tips cleaned.", "resolutions": [{"item_id": item_id, "returned": 2}],
    }, format="json")

    assert returned.status_code == 200, returned.data
    request.refresh_from_db()
    product.refresh_from_db()
    assert request.status == HardwareRequest.Status.RETURNED
    assert (product.available_quantity, product.issued_quantity) == (3, 0)


def test_checkin_machine_job_completes_and_is_collected_without_payment():
    space = _space("checkin-machine-job")
    manager = make_member("checkin-machine-manager", space)
    machine_type = MachineType.objects.create(
        makerspace=space, slug="embroidery", name="Embroidery machine",
        capability_config={"metering_unit": "count", "requires_booking": False},
    )
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Brother PE800")

    with _roster(mid=4402, name="Rahul Nair"):
        submitted = APIClient().post(
            f"/api/v1/public/{space.slug}/machine-service-requests",
            {"checkin_mid": 4402, "name": "Rahul Nair", "machine_id": machine.id, "title": "Club badges"},
            format="json",
        )
    assert submitted.status_code == 201, submitted.data
    job = MachineServiceRequest.objects.get()

    staff = _staff(manager)
    for action, body in (("accept", {"estimated_minutes": 60}), ("start", {"machine_id": machine.id}),
                         ("complete", {"actual_minutes": 70}), ("collect", {})):
        response = staff.post(f"/api/v1/admin/machine-service/requests/{job.id}/{action}", body, format="json")
        assert response.status_code == 200, (action, response.data)

    job.refresh_from_db()
    assert job.status == MachineServiceRequest.Status.COLLECTED
    # Payments is off: completion must neither raise nor require a charge.
    assert not Payment.objects.filter(makerspace=space).exists()
