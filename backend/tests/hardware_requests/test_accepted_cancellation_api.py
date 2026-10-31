"""Portable causal RED: this entire file also runs before cancellation migrations."""
import json

import pytest

from apps.audit.models import AuditLog
from tests.test_request_workflow import (
    accept_url, authenticated_client, make_hardware_request, make_member,
    make_product, make_space,
)

pytestmark = pytest.mark.django_db


def test_real_accept_then_cancel_releases_only_the_approved_reservation():
    # All setup and imports predate cancellation. In the old source frame the FIRST
    # failure must be the actual cancel HTTP status below (404 instead of 200).
    space = make_space("portable-cancel")
    actor = make_member("portable-reviewer", space)
    product = make_product(space, total_quantity=5, available_quantity=5)
    request = make_hardware_request(space, product, quantity=4)
    item = request.items.get()
    client = authenticated_client(actor)
    accepted = client.post(accept_url(request), {"accepted_quantities": [
        {"item_id": item.pk, "quantity": 2},
    ]}, format="json")
    assert accepted.status_code == 200
    product.refresh_from_db()
    request.refresh_from_db()
    item.refresh_from_db()
    assert (product.available_quantity, product.reserved_quantity) == (3, 2)
    assert item.accepted_quantity == 2
    approval = (request.accepted_by_id, request.accepted_at)
    approval_event = AuditLog.objects.get(action="request.accepted", target_id=str(request.pk))
    approval_meta = approval_event.meta.copy()

    response = client.post(f"/api/v1/admin/requests/{request.pk}/cancel",
                           {"reason": "  Plans changed: private borrower detail.  "}, format="json")

    assert response.status_code == 200
    assert response.data["status"] == "cancelled"
    assert response.data["cancellation_reason"] == "Plans changed: private borrower detail."
    assert response.data["closed_by"] == {"username": actor.username, "role": actor.role}
    assert response.data["closed_at"]
    request.refresh_from_db()
    product.refresh_from_db()
    item.refresh_from_db()
    assert request.status == "cancelled"
    assert request.closed_by_id == actor.pk and request.closed_at is not None
    assert request.assigned_box_id is None
    assert (request.accepted_by_id, request.accepted_at) == approval
    assert (item.requested_quantity, item.accepted_quantity, item.issued_quantity) == (4, 2, 0)
    assert (product.available_quantity, product.reserved_quantity,
            product.issued_quantity, product.total_quantity) == (5, 0, 0, 5)
    approval_event.refresh_from_db()
    assert approval_event.meta == approval_meta
    event = AuditLog.objects.get(action="request.cancelled", target_id=str(request.pk))
    assert (event.makerspace_id, event.actor_id) == (space.pk, actor.pk)
    assert event.target_type == request._meta.label_lower
    assert event.meta == {"reason_recorded": True}
    assert "private borrower detail" not in json.dumps(event.meta)
