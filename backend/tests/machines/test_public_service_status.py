"""Opaque service links expose the real lifecycle with no identity or machine details."""
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.machines import role_scope
from apps.machines.models import Machine, MachineServiceRequest
from apps.machines.service_workflow import accept, start
from tests.machines.public_service_helpers import post_request, service_lab

pytestmark = pytest.mark.django_db

STATUS_KEYS = {"public_token", "status", "title", "created_at", "accepted_at", "started_at", "completed_at",
               "estimated_minutes", "queue_position", "queue_approved_ahead", "queue_awaiting_review_ahead"}


def test_token_tracks_actual_generic_in_progress_with_strict_safe_allowlist(service_lab):
    space, actor, _, generic, _ = service_lab
    submitted = post_request(service_lab)
    assert submitted.status_code == 201, submitted.data
    row = MachineServiceRequest.objects.get()
    accept(row, actor, estimated_minutes=25)
    machine = Machine.objects.get(makerspace=space, machine_type=generic)
    start(row, actor, role_scope.EXEMPT, machine_id=machine.pk)
    response = APIClient().get(reverse("public-machine-service-status", args=[row.public_token]))
    assert response.status_code == 200, response.data
    assert set(response.data) == STATUS_KEYS and response.data["status"] == "in_progress"
    assert response.data["started_at"] and response.data["estimated_minutes"] == 25
    for secret in (actor.email, actor.phone, actor.display_name):
        assert secret not in str(response.data)


@pytest.mark.parametrize("gate", ["machines", "machine_service", "printing", "archived", "inactive"])
def test_token_denial_is_indistinguishable_from_an_unknown_token(service_lab, gate):
    space, _, _, _, printer = service_lab
    response = post_request(service_lab, printer)
    assert response.status_code == 201
    token = response.data["public_token"]
    if gate == "archived":
        space.archived_at = timezone.now()
    elif gate == "inactive":
        space.lifecycle_state = "importing"
    else:
        space.enabled_modules.remove(gate)
        if gate == "machine_service":
            space.enabled_modules.remove("printing")
    space.save()
    client = APIClient()
    unavailable = client.get(reverse("public-machine-service-status", args=[token]))
    unknown = client.get(reverse("public-machine-service-status", args=[uuid4()]))
    assert unavailable.status_code == unknown.status_code == 404
    assert unavailable.data == unknown.data


def test_existing_printer_token_works_on_both_status_routes(service_lab):
    response = post_request(service_lab, service_lab[-1])
    assert response.status_code == 201
    token = response.data["public_token"]
    for route in ("public-printer-service-status", "public-machine-service-status"):
        tracked = APIClient().get(reverse(route, args=[token]))
        assert tracked.status_code == 200 and set(tracked.data) == STATUS_KEYS
        assert str(tracked.data["public_token"]) == token and tracked.data["status"] == "pending"
