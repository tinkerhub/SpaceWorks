"""Checked-in walk-ins can use the public machine-service submission surfaces."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.checkin.client import CheckinEntry
from apps.checkin.models import CheckinIdentity
from apps.machines.models import (
    Machine,
    MachineServiceRequest,
    MachineType,
    ServiceQueue,
)
from apps.machines.printer_capabilities import PRINTER_CONFIG
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.request_access import MODE_CHECKED_IN, MODE_DISABLED


pytestmark = pytest.mark.django_db


def _space(slug, *, mode=MODE_CHECKED_IN):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        # `printing` as well as `machine_service`: the 3D-printer surfaces gained their own
        # module gate, and that check runs BEFORE authentication, so without it even the
        # unauthenticated cases return 400 "printing is disabled" instead of 401.
        enabled_modules=["machine_service", "printing"],
        public_request_mode=mode,
        checkin_space_id=1 if mode == MODE_CHECKED_IN else None,
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


def _roster(*entries):
    return patch("apps.checkin.client.fetch_roster", return_value=list(entries))


def _printer_queue(space):
    printer_type, _ = MachineType.objects.get_or_create(
        makerspace=None,
        slug="3d_printer",
        defaults={
            "name": "3D Printer",
            "is_builtin": True,
            "capability_config": PRINTER_CONFIG,
        },
    )
    return ServiceQueue.objects.create(
        makerspace=space,
        machine_type=printer_type,
        name="Public print queue",
    )


def test_checked_in_walk_in_can_submit_a_machine_service_request():
    space = _space("checkin-machine-service")
    machine_type = MachineType.objects.create(
        makerspace=space, slug="laser", name="Laser"
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Laser cutter"
    )

    with _roster(_entry()):
        response = APIClient().post(
            reverse("public-machine-service-request-submit", args=[space.slug]),
            {
                "checkin_mid": 443,
                "name": "ada   example",
                "machine_id": machine.pk,
                "title": "Cut enclosure",
            },
            format="json",
        )

    assert response.status_code == 201, response.content
    row = MachineServiceRequest.objects.get(makerspace=space)
    identity = CheckinIdentity.objects.get(makerspace=space)
    assert row.requester_id == row.member_id == identity.user_id
    assert row.requester_name == "Ada Example"
    assert not MakerspaceMembership.objects.filter(user_id=identity.user_id).exists()


def test_checked_in_walk_in_can_submit_a_printer_request():
    space = _space("checkin-printer-request")
    queue = _printer_queue(space)

    with _roster(_entry()):
        response = APIClient().post(
            reverse("public-printer-service-request", args=[space.slug]),
            {
                "checkin_mid": 443,
                "name": "Ada Example",
                "queue_id": queue.pk,
                "title": "Print enclosure",
            },
            format="json",
        )

    assert response.status_code == 201, response.content
    row = MachineServiceRequest.objects.get(makerspace=space)
    identity = CheckinIdentity.objects.get(makerspace=space)
    assert row.requester_id == row.member_id == identity.user_id
    assert row.requester_name == "Ada Example"


def test_checked_in_walk_in_owns_their_staged_printer_upload():
    space = _space("checkin-printer-upload")
    queue = _printer_queue(space)

    with (
        _roster(_entry()),
        patch(
            "apps.machines.views_public_printer_service.stage_upload",
            return_value={"file_id": 17, "upload": {}},
        ) as stage_upload,
    ):
        response = APIClient().post(
            reverse("public-printer-service-upload", args=[space.slug]),
            {
                "checkin_mid": 443,
                "name": "Ada Example",
                "queue_id": queue.pk,
                "kind": "stl",
                "filename": "part.stl",
            },
            format="json",
        )

    assert response.status_code == 201, response.content
    identity = CheckinIdentity.objects.get(makerspace=space)
    assert stage_upload.call_args.args[2].pk == identity.user_id


@pytest.mark.parametrize(
    ("view_name", "payload"),
    [
        ("public-machine-service-request-submit", {}),
        ("public-printer-service-upload", {}),
        ("public-printer-service-request", {}),
    ],
)
def test_non_checkin_policies_keep_the_unauthenticated_401(view_name, payload):
    space = _space(f"{view_name}-auth", mode=MODE_DISABLED)

    response = APIClient().post(
        reverse(view_name, args=[space.slug]), payload, format="json"
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication credentials were not provided."
    }


def test_mid_throttle_is_charged_before_the_upstream_roster_call(monkeypatch):
    from apps.checkin.throttles import CheckinMidThrottle

    space = _space("checkin-machine-throttle")
    machine_type = MachineType.objects.create(
        makerspace=space, slug="router", name="Router"
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="CNC router"
    )
    order = []

    def allow_request(throttle, request, view):
        order.append(("throttle", request.checkin_mid, request.checkin_makerspace_id))
        return True

    def fetch_roster(*, cached):
        order.append(("upstream", cached))
        return [_entry()]

    monkeypatch.setattr(CheckinMidThrottle, "allow_request", allow_request)
    monkeypatch.setattr("apps.checkin.client.fetch_roster", fetch_roster)

    response = APIClient().post(
        reverse("public-machine-service-request-submit", args=[space.slug]),
        {
            "checkin_mid": 443,
            "name": "Ada Example",
            "machine_id": machine.pk,
            "title": "Route panel",
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    assert order == [("throttle", 443, space.pk), ("upstream", False)]
