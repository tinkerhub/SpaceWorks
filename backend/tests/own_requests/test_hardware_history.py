"""Real HTTP projection: ownership, stable pages and exact per-request quantities."""

from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import MakerspaceMembership
from apps.notifications.models import Notification
from tests.own_requests.own_requests_support import (
    ITEM_KEYS, hardware, history_lab, history_url, providers,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("status", HardwareRequest.Status.values)
def test_owner_reads_every_actual_status_without_membership_or_roster(history_lab, status):
    lab = history_lab
    row = hardware(lab, status=status, cancellation_reason="Private cancellation",
                   requester_contact_email="secret@example.test")
    hardware(lab, owner=lab.other)
    hardware(lab, space=lab.other_space)
    Notification.objects.create(makerspace=lab.space, title="Staff only", body="Private inbox")
    assert not MakerspaceMembership.objects.filter(user=lab.user).exists()
    assert "membership" not in lab.space.enabled_modules
    assert "member_accounts" not in lab.space.enabled_modules

    response = lab.client.get(history_url(lab))

    assert response.status_code == 200, response.data
    assert set(response.data) == {"count", "next", "previous", "results"}
    assert response.data["count"] == 1
    assert response.data["next"] is response.data["previous"] is None
    result = response.data["results"][0]
    assert set(result) == {"public_token", "status", "created_at", "items"}
    assert str(result["public_token"]) == str(row.public_token)
    assert result["status"] == status and result["created_at"]
    assert result["items"] == [{
        "product_name": lab.product.name, "requested_quantity": 7,
        "accepted_quantity": 5, "issued_quantity": 4, "returned_quantity": 2,
    }]
    assert set(result["items"][0]) == ITEM_KEYS


def test_count_is_filtered_before_stable_twenty_four_row_pages(history_lab):
    lab = history_lab
    rows = [hardware(lab) for _ in range(25)]
    for _ in range(3):
        hardware(lab, owner=lab.other)
        hardware(lab, space=lab.other_space)
    # Equal timestamps force the documented descending PK tie-breaker.
    HardwareRequest.objects.filter(pk__in=[r.pk for r in rows]).update(created_at=timezone.now())
    expected = [str(r.public_token) for r in reversed(rows)]
    first = lab.client.get(history_url(lab))
    assert first.status_code == 200 and first.data["count"] == 25
    assert len(first.data["results"]) == 24 and first.data["previous"] is None
    next_url = urlsplit(first.data["next"])
    second = lab.client.get(next_url.path + "?" + next_url.query)
    assert second.status_code == 200 and second.data["count"] == 25
    assert len(second.data["results"]) == 1 and second.data["next"] is None
    assert second.data["previous"]
    actual = [str(r["public_token"]) for r in first.data["results"] + second.data["results"]]
    assert actual == expected and len(set(actual)) == 25


def test_anonymous_bearer_status_keeps_safe_partial_totals_and_wrong_token_denial(history_lab, settings):
    lab = history_lab
    row = hardware(lab, status="partially_returned", cancellation_reason="Private reason")
    path = reverse("hardware_requests:request-status", args=[row.public_token])
    response = APIClient().get(path)
    assert response.status_code == 200
    assert set(response.data) == {"status", "created_at", "items"}
    assert response.data["items"] == [{
        "product_name": lab.product.name, "requested_quantity": 7,
        "accepted_quantity": 5, "issued_quantity": 4, "returned_quantity": 2,
    }]
    assert APIClient().get(reverse("hardware_requests:request-status", args=[uuid4()])).status_code == 404

    # Preserve the existing publishable-key origin fence on bearer-status reads.
    settings.API_CLIENT_AUTH_REQUIRED = True
    lab.space.public_inventory_enabled = True
    lab.space.frontend_domain = "own-history.example.test"
    lab.space.frontend_domain_status = "verified"
    lab.space.save(update_fields=["public_inventory_enabled", "frontend_domain", "frontend_domain_status"])
    headers = {"HTTP_X_PUBLISHABLE_KEY": lab.space.public_api_key}
    assert APIClient().get(path, HTTP_ORIGIN="https://own-history.example.test", **headers).status_code == 200
    assert APIClient().get(path, HTTP_ORIGIN="https://foreign-history.example.test", **headers).status_code == 401
