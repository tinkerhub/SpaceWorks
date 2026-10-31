"""Actual competing accepts must never reserve the same last physical unit twice."""
import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.hardware_requests import request_workflow
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItemAsset
from apps.inventory.models import InventoryAsset, TrackingMode
from tests.inventory_lending_concurrency_helpers import race_accepts
from tests.inventory_lending_helpers import assert_surfaces, make_lab, submit_request

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("tracking_mode", [TrackingMode.QUANTITY, TrackingMode.INDIVIDUAL])
def test_two_actual_accepts_for_last_unit_have_one_winner(monkeypatch, settings, tracking_mode):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks, pg_blocking_pids and separate connections")
    assert not connection.in_atomic_block and connection.get_autocommit()
    lab = make_lab(monkeypatch, settings, total=1, tracking_mode=tracking_mode)
    first = submit_request(lab, quantity=1, suffix="race-first")
    second = submit_request(lab, quantity=1, suffix="race-second")
    pending = HardwareRequest.Status.PENDING_APPROVAL
    accepted = HardwareRequest.Status.ACCEPTED
    assert_surfaces(lab, 1, 0, 0, {first.pk: pending, second.pk: pending})
    asset_before = list(
        lab.product.assets.order_by("pk").values_list("pk", "status", "box_id")
    )
    reached, release = threading.Event(), threading.Event()
    real_record = request_workflow.audit.record

    def pause_after_real_accept_audit(actor, action, **kwargs):
        event = real_record(actor, action, **kwargs)
        target = kwargs.get("target")
        if action == "request.accepted" and target is not None and target.pk == first.pk:
            # The canonical accept has reserved under SELECT FOR UPDATE and has
            # written its real audit event; its outer transaction is still open.
            reached.set()
            assert release.wait(12), "Timed out releasing the first accept"
        return event

    monkeypatch.setattr(request_workflow.audit, "record", pause_after_real_accept_audit)

    def accept_request(request_id):
        # Each worker owns its API client and actor instance, as well as its DB session.
        actor = get_user_model().objects.get(pk=lab.actor.pk)
        client = APIClient()
        client.force_authenticate(user=actor)
        return client.post(f"/api/v1/admin/requests/{request_id}/accept", {}, format="json")

    winner, loser, pids = race_accepts(
        lambda: accept_request(first.pk), lambda: accept_request(second.pk), reached, release,
    )
    assert len(set(pids.values())) == 2
    assert [winner.status_code, loser.status_code] == [200, 409]
    assert winner.data["id"] == first.pk and winner.data["status"] == accepted
    assert set(loser.data) == {"detail", "code"}
    assert loser.data["code"] == "insufficient_stock"
    assert loser.data["detail"]

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == accepted and first.accepted_by_id == lab.actor.pk
    assert first.accepted_at is not None
    assert second.status == pending and second.accepted_by_id is None
    assert second.accepted_at is None
    assert first.items.get().accepted_quantity == 1
    refused_item = second.items.get()
    # The contender's item save precedes reservation; the stock refusal must roll it back.
    assert (
        refused_item.accepted_quantity, refused_item.issued_quantity,
        refused_item.returned_quantity, refused_item.damaged_quantity,
        refused_item.missing_quantity, refused_item.needs_fix_quantity,
    ) == (0, 0, 0, 0, 0, 0)
    assert not HardwareRequestItemAsset.objects.filter(
        request_item__request__makerspace=lab.space,
    ).exists()
    assert list(lab.product.assets.order_by("pk").values_list("pk", "status", "box_id")) == asset_before
    if tracking_mode == TrackingMode.INDIVIDUAL:
        assert len(asset_before) == 1
        # Accept reserves a quantity; serialized rows remain AVAILABLE until issue.
        assert asset_before[0][1] == InventoryAsset.Status.AVAILABLE
        assert lab.product.assets.filter(status=InventoryAsset.Status.RESERVED).count() == 0
    else:
        assert asset_before == []
    events = AuditLog.objects.filter(makerspace=lab.space, action="request.accepted")
    assert list(events.values_list("target_id", "actor_id")) == [(str(first.pk), lab.actor.pk)]
    assert_surfaces(lab, 0, 1, 0, {first.pk: accepted, second.pk: pending})
    lab.product.refresh_from_db()
    assert (
        lab.product.total_quantity, lab.product.available_quantity,
        lab.product.reserved_quantity, lab.product.issued_quantity,
        lab.product.damaged_quantity, lab.product.lost_quantity,
        lab.product.needs_fix_quantity,
    ) == (1, 0, 1, 0, 0, 0, 0)
