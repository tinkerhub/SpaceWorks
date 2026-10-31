"""Member ownership and canonical queue counts through the public history API."""

from urllib.parse import urlsplit

import pytest
from django.utils import timezone

from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue
from tests.own_requests.own_requests_support import (
    MACHINE_KEYS, ROUTES, history_lab, history_url, providers, service,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("status", MachineServiceRequest.Status.values)
def test_only_member_owns_history_even_when_legacy_requester_matches(history_lab, status):
    lab = history_lab
    owned = service(lab, member=lab.user, requester=lab.other, status=status,
                    contact_email="private@example.test", reason="Private reason",
                    source_link="https://secret.invalid/file")
    service(lab, member=None, requester=lab.user,
            requester_name=lab.user.username, contact_email=lab.user.email)
    service(lab, member=lab.other, requester=lab.user,
            requester_name=lab.user.username, contact_email=lab.user.email)
    foreign_type = MachineType.objects.create(makerspace=lab.other_space, slug="lathe", name="Lathe")
    foreign_queue = ServiceQueue.objects.create(
        makerspace=lab.other_space, machine_type=foreign_type, name="Foreign queue",
    )
    service(lab, queue=foreign_queue, member=lab.user)

    response = lab.client.get(history_url(lab, ROUTES[1]))

    assert response.status_code == 200, response.data
    assert set(response.data) == {"count", "next", "previous", "results"}
    assert response.data["count"] == 1
    result = response.data["results"][0]
    assert set(result) == MACHINE_KEYS
    assert str(result["public_token"]) == str(owned.public_token)
    assert result["title"] == owned.title and result["status"] == status
    assert "member_accounts" not in lab.space.enabled_modules
    assert not lab.user.makerspace_memberships.exists()


def test_waiting_rank_counts_real_other_work_without_exposing_its_rows(history_lab):
    lab = history_lab
    service(lab, member=lab.other, title="Other pending")
    service(lab, member=lab.other, status="accepted", title="Other approved")
    owned = service(lab, member=lab.user)
    service(lab, member=lab.other, title="Later pending")
    service(lab, member=lab.other, status="completed", title="Finished")

    response = lab.client.get(history_url(lab, ROUTES[1]))

    assert response.status_code == 200 and response.data["count"] == 1
    result = response.data["results"][0]
    assert str(result["public_token"]) == str(owned.public_token)
    assert (result["queue_position"], result["queue_approved_ahead"],
            result["queue_awaiting_review_ahead"]) == (3, 1, 1)
    assert set(result) == MACHINE_KEYS


def test_machine_history_also_pages_at_twenty_four_with_stable_ties(history_lab):
    lab = history_lab
    rows = [service(lab, member=lab.user, status="completed") for _ in range(25)]
    service(lab, member=lab.other)
    MachineServiceRequest.objects.filter(pk__in=[r.pk for r in rows]).update(created_at=timezone.now())
    first = lab.client.get(history_url(lab, ROUTES[1]))
    assert first.status_code == 200 and first.data["count"] == 25
    assert len(first.data["results"]) == 24 and first.data["previous"] is None
    next_url = urlsplit(first.data["next"])
    second = lab.client.get(next_url.path + "?" + next_url.query)
    assert second.status_code == 200 and second.data["count"] == 25
    assert second.data["next"] is None and second.data["previous"]
    actual = [str(r["public_token"]) for r in first.data["results"] + second.data["results"]]
    assert actual == [str(r.public_token) for r in reversed(rows)]
    assert len(set(actual)) == 25
