"""Typed submit and upload share active-member and upstream-principal boundaries."""
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.checkin.client import CheckinUnavailable
from apps.checkin.models import CheckinIdentity
from apps.checkin.throttles import CheckinMidThrottle, CheckinMidUploadThrottle
from apps.machines.models import MachineServiceRequest, ServiceQueue, ServiceRequestFile
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole, MakerspaceWaiver
from apps.makerspaces.waiver_services import accept_waiver
from apps.presence import services as presence
from tests.checkin.test_machine_service_views import _entry
from tests.machines.public_service_helpers import endpoint, object_io, service_lab

pytestmark = pytest.mark.django_db(transaction=True)


def body(kind, action):
    return {"machine_type_id": kind.pk, **({"title": "Panel"} if action == "submit" else {
        "filename": "panel.pdf", "content_type": "application/pdf", "kind": "attachment",
    })}


@pytest.mark.parametrize("action", ["submit", "upload"])
@pytest.mark.parametrize("identity", ["anonymous", "inactive", "restricted", "no_membership", "no_waiver", "no_presence", "ready"])
def test_identity_and_membership_guards_run_before_setup(service_lab, object_io, action, identity):
    space, actor, client, generic, _ = service_lab
    if identity == "anonymous":
        client = APIClient()
    elif identity in {"inactive", "restricted"}:
        if identity == "inactive":
            actor.is_active = False
        else:
            actor.access_status = "restricted"
        actor.save()
    else:
        space.enabled_modules.append("membership")
        space.save(update_fields=["enabled_modules"])
        MakerspaceWaiver.objects.create(makerspace=space, version="v1", body="Take care", is_active=True)
        if identity != "no_membership":
            membership = MakerspaceMembership.objects.create(makerspace=space, user=actor, role="custom", assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"))
            if identity != "no_waiver":
                accept_waiver(membership)
            if identity == "ready":
                presence.start_session(actor, space, 60)
    response = client.post(endpoint(space, action), body(generic, action), format="json")
    assert response.status_code == (201 if identity == "ready" else 401 if identity == "anonymous" else 403), response.data
    if identity != "ready":
        assert not ServiceQueue.objects.exists() and not ServiceRequestFile.objects.exists()
        assert not MachineServiceRequest.objects.exists()
        assert object_io[1].mock_calls == object_io[2].mock_calls == []


@pytest.mark.parametrize("action", ["submit", "upload"])
def test_checked_in_principal_replaces_logged_in_account_and_mid_is_throttled_first(service_lab, object_io, monkeypatch, action):
    cache.clear()
    space, actor, client, generic, _ = service_lab
    space.public_request_mode, space.checkin_space_id = "checked_in", 1
    space.save(update_fields=["public_request_mode", "checkin_space_id"])
    order = []
    throttle = CheckinMidThrottle if action == "submit" else CheckinMidUploadThrottle

    def allow(self, request, view):
        order.append(("throttle", request.checkin_mid, request.checkin_makerspace_id))
        return True

    def roster(makerspace=None, *, cached):
        order.append(("roster", cached))
        return [_entry()]

    monkeypatch.setattr(throttle, "allow_request", allow)
    monkeypatch.setattr("apps.checkin.client.fetch_roster", roster)
    response = client.post(endpoint(space, action), {**body(generic, action), "checkin_mid": 443, "name": "ada   example"}, format="json")
    assert response.status_code == 201, response.data
    assert order == [("throttle", 443, space.pk), ("roster", False)]
    principal = CheckinIdentity.objects.get(makerspace=space)
    assert principal.user_id != actor.pk
    assert not MakerspaceMembership.objects.filter(user_id=principal.user_id).exists()
    if action == "submit":
        row = MachineServiceRequest.objects.get()
        assert row.member_id == row.requester_id == principal.user_id and row.requester_name == "Ada Example"
    else:
        file = ServiceRequestFile.objects.get()
        assert file.owner_user_id == principal.user_id


@pytest.mark.parametrize("action", ["submit", "upload"])
@pytest.mark.parametrize("failure", ["missing_mid", "missing_name", "mismatch", "absent", "unavailable", "throttled"])
def test_checked_in_policy_fails_closed_without_account_identity_bypass(service_lab, object_io, monkeypatch, action, failure):
    cache.clear()
    space, _, client, generic, _ = service_lab
    space.public_request_mode, space.checkin_space_id = "checked_in", 1
    space.save(update_fields=["public_request_mode", "checkin_space_id"])
    roster = Mock(return_value=[] if failure == "absent" else [_entry()])
    if failure == "unavailable":
        roster.side_effect = CheckinUnavailable()
    monkeypatch.setattr("apps.checkin.client.fetch_roster", roster)
    throttle = CheckinMidThrottle if action == "submit" else CheckinMidUploadThrottle
    if failure == "throttled":
        monkeypatch.setattr(throttle, "allow_request", lambda *args: False)
        monkeypatch.setattr(throttle, "wait", lambda *args: 60)
    payload = {**body(generic, action), "checkin_mid": 443, "name": "Wrong Person" if failure == "mismatch" else "Ada Example"}
    if failure == "missing_mid":
        payload.pop("checkin_mid")
    if failure == "missing_name":
        payload.pop("name")
    response = client.post(endpoint(space, action), payload, format="json")
    expected = 503 if failure == "unavailable" else 429 if failure == "throttled" else 403 if failure in {"mismatch", "absent"} else 400
    assert response.status_code == expected, response.data
    if failure in {"missing_mid", "missing_name", "throttled"}:
        roster.assert_not_called()
    assert not ServiceQueue.objects.exists() and not ServiceRequestFile.objects.exists()
    assert not MachineServiceRequest.objects.exists() and not CheckinIdentity.objects.exists()
    assert object_io[1].mock_calls == object_io[2].mock_calls == []
