"""Canonical stock setup and cross-surface assertions for lending regressions."""
from types import SimpleNamespace

from rest_framework.test import APIClient

from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.request_workflow import RequesterSnapshot
from apps.integrations.notify import NotificationResult
from apps.inventory.models import InventoryAsset, PublicAvailabilityMode, TrackingMode
from apps.operations.services_qr_assets import generate_assets_with_qr
from tests.return_helpers import authenticated_client, make_member, make_product, make_space, make_user
from tests.test_public_inventory import PUBLIC_PRODUCT_FIELDS


def make_lab(monkeypatch, settings, *, total=3, tracking_mode=TrackingMode.QUANTITY):
    settings.API_CLIENT_AUTH_REQUIRED = False
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    # Notification adapter only: validators, workflow, RBAC and audits remain real.
    monkeypatch.setattr(
        "apps.hardware_requests.notifications.notify_lifecycle",
        lambda *args, **kwargs: NotificationResult(scheduled=False),
    )
    space = make_space("inventory-lending")
    actor = make_member("lending-manager", space)
    initial = 0 if tracking_mode == TrackingMode.INDIVIDUAL else total
    product = make_product(
        space, tracking_mode=tracking_mode, total_quantity=initial,
        available_quantity=initial, show_public_count=True,
        public_availability_mode=PublicAvailabilityMode.EXACT_COUNT,
        storage_location="Private cabinet 19",
    )
    generated = []
    if tracking_mode == TrackingMode.INDIVIDUAL:
        generated, _ = generate_assets_with_qr(actor, product, {"count": total})
    return SimpleNamespace(
        space=space, actor=actor, product=product, total=total,
        assets=[row["asset"] for row in generated],
        qrs=[row["qr"] for row in generated],
        client=authenticated_client(actor), public=APIClient(),
    )


def submit_request(lab, quantity=2, suffix="borrower"):
    borrower = make_user(suffix, access_status="active")
    return workflow.submit_request(
        lab.space, [{"product": lab.product, "quantity": quantity}],
        requested_for="Bench diagnostics", requester_principal=borrower,
        contact_snapshot=RequesterSnapshot(
            username=borrower.username, name="Private Borrower",
            email=borrower.email, phone="+15550101010", contact_verified=True,
        ), audit_actor=borrower,
    )


def _get(client, url):
    response = client.get(url)
    assert response.status_code == 200, response.data
    return response.data


def _rows(client, url):
    data = _get(client, url)
    assert set(data) == {"count", "next", "previous", "results"}
    assert data["next"] is None and data["previous"] is None
    assert data["count"] == len(data["results"])
    return data["results"]


def assert_surfaces(lab, available, reserved, issued, states):
    """Each committed phase must agree in public reads, staff reads and storage."""
    lab.product.refresh_from_db()
    expected = {
        "total_quantity": lab.total, "available_quantity": available,
        "reserved_quantity": reserved, "issued_quantity": issued,
        "damaged_quantity": 0, "lost_quantity": 0, "needs_fix_quantity": 0,
    }
    assert {key: getattr(lab.product, key) for key in expected} == expected
    assert available + reserved + issued == lab.total
    assert min(available, reserved, issued) >= 0
    assert dict(HardwareRequest.objects.filter(makerspace=lab.space).values_list("pk", "status")) == states

    public_url = f"/api/v1/public/{lab.space.slug}/inventory/"
    public_rows = _rows(lab.public, public_url)
    assert len(public_rows) == 1
    detail = _get(lab.public, f"{public_url}{lab.product.pk}/")
    label = "Unavailable" if available == 0 else ("Limited" if available == 1 else "Available")
    for row in [public_rows[0], detail]:
        # Exact allowlist excludes internal buckets, locations, QR, evidence and PII.
        assert set(row) == PUBLIC_PRODUCT_FIELDS
        assert row["id"] == lab.product.pk
        assert row["availability"] == {"mode": "exact_count", "count": available, "label": label}
    assert detail == public_rows[0]

    staff_base = f"/api/v1/admin/makerspace/{lab.space.pk}"
    inventory = _rows(lab.client, f"{staff_base}/inventory")
    assert len(inventory) == 1
    staff_detail = _get(lab.client, f"/api/v1/admin/inventory/{lab.product.pk}")
    for row in [inventory[0], staff_detail]:
        assert row["id"] == lab.product.pk
        assert {key: row[key] for key in expected} == expected
        assert row["storage_location"] == "Private cabinet 19"

    queues = {
        "pending-requests": {"pending_approval"}, "accepted-requests": {"accepted"},
        "active-loans": {"issued", "partially_returned"},
        "request-history": {"returned", "rejected", "closed_with_issue"},
    }
    for endpoint, statuses in queues.items():
        rows = _rows(lab.client, f"{staff_base}/{endpoint}")
        assert {row["id"] for row in rows} == {pk for pk, status in states.items() if status in statuses}
        for row in rows:
            loan = HardwareRequest.objects.get(pk=row["id"])
            item = loan.items.get()
            assert row["status"] == states[loan.pk]
            assert row["assigned_box_id"] == loan.assigned_box_id
            assert row["issue_evidence_id"] == loan.issue_evidence_id
            assert set(row["return_evidence_ids"]) == set(loan.returnevent_set.values_list("evidence_id", flat=True))
            assert len(row["items"]) == 1
            actual = row["items"][0]
            for field in ("requested_quantity", "accepted_quantity", "issued_quantity", "returned_quantity"):
                assert actual[field] == getattr(item, field)
            assert actual["product_id"] == lab.product.pk
            assert actual["storage_location"] == "Private cabinet 19"
            assert {asset["asset_id"] for asset in actual["issued_assets"]} == set(
                item.asset_links.filter(outcome="issued").values_list("asset_id", flat=True)
            )

    counts = _get(lab.client, f"{staff_base}/dashboard")
    assert counts["scope_mode"] == "full"
    assert counts["pending_requests"] == list(states.values()).count("pending_approval")
    assert counts["awaiting_issue"] == list(states.values()).count("accepted")
    assert counts["low_stock"] == int(available == 0)
    if lab.assets:
        physical = list(InventoryAsset.objects.filter(product=lab.product).values_list("status", flat=True))
        assert len(physical) == lab.total
        assert physical.count("issued") == issued
        # Reservations do not change unit status until physical handover.
        assert physical.count("available") == available + reserved
