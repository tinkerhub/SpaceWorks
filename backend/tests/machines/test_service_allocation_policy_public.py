"""Staff allocation policy never widens public service response allowlists."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.machines.models import MachineServiceRequest, ServiceQueue
from tests.machines.public_service_helpers import post_request, service_lab
from tests.own_requests.own_requests_support import MACHINE_KEYS


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("policy", ["staff_select", "first_idle"])
@pytest.mark.parametrize("printer", [False, True], ids=["generic", "printer"])
def test_public_submit_token_status_and_own_history_keep_exact_safe_shapes(service_lab, policy, printer):
    space, actor, client, generic, printer_type = service_lab
    kind = printer_type if printer else generic
    queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=kind, name="Configured allocation queue",
        allocation_policy=policy,
    )

    submitted = post_request(service_lab, kind)

    assert submitted.status_code == 201, submitted.data
    assert set(submitted.data) == {"public_token", "status"}
    row = MachineServiceRequest.objects.get(public_token=submitted.data["public_token"])
    assert (row.queue_id, row.member_id) == (queue.pk, actor.pk)
    routes = ["public-machine-service-status"]
    if printer:
        routes.append("public-printer-service-status")
    for route in routes:
        status = APIClient().get(reverse(route, args=[row.public_token]))
        assert status.status_code == 200, status.data
        assert set(status.data) == MACHINE_KEYS
        assert str(status.data["public_token"]) == str(row.public_token)
        assert status.data["status"] == "pending"
        assert "allocation_policy" not in status.data

    history = client.get(reverse("public-own-machine-service-requests", args=[space.slug]))

    assert history.status_code == 200, history.data
    assert set(history.data) == {"count", "next", "previous", "results"}
    assert history.data["count"] == 1
    assert len(history.data["results"]) == 1
    owned = history.data["results"][0]
    assert set(owned) == MACHINE_KEYS
    assert str(owned["public_token"]) == str(row.public_token)
    assert "allocation_policy" not in owned
    queue.refresh_from_db()
    assert queue.allocation_policy == policy
