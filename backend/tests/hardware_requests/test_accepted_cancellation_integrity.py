"""Reservation attribution, immutable history, and fail-closed legacy corruption."""
import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.boxes.models import Box, BoxScan, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import (
    HardwareRequest, HardwareRequestItem, HardwareRequestItemAsset, PublicToolLoan,
    RequesterAccountability, ReturnEvent,
)
from apps.inventory.models import InventoryAsset, InventoryProduct
from tests.test_request_workflow import make_hardware_request, make_product, make_space
from tests.hardware_requests.cancellation_support import (
    accept, accepted_lab, assignment, buckets, cancel, photo, refused, snapshot,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("tracking,physical_reserved", [("quantity", 0), ("individual", 0),
                                                       ("individual", 1)])
def test_partial_duplicate_lines_release_own_demand_and_preserve_physical_stock(tracking, physical_reserved):
    lab = accepted_lab(tracking=tracking, physical_reserved=physical_reserved,
                       lines=[(4, 2), (3, 1), (1, 0)])
    other = make_hardware_request(lab.space, lab.product, quantity=1)
    accept(lab.client, other)
    before_other = HardwareRequest.objects.filter(pk=other.pk).values().get()
    before_lines = list(lab.request.items.order_by("pk").values())
    before_assets = list(InventoryAsset.objects.order_by("pk").values())
    approval = (lab.request.accepted_by_id, lab.request.accepted_at)
    assert buckets(lab.product) == (4 - physical_reserved, 4 + physical_reserved, 0, 8)
    box = assignment(lab)
    photo(lab)  # Uploaded but unattached metadata is legitimate before handover.
    retained = {model: list(model.objects.order_by("pk").values())
                for model in (Box, BoxScan, QrScanEvent, EvidencePhoto)}

    response = cancel(lab)

    assert response.status_code == 200, response.content
    assert buckets(lab.product) == (7 - physical_reserved, 1 + physical_reserved, 0, 8)
    lab.request.refresh_from_db()
    assert lab.request.assigned_box_id is None
    assert (lab.request.accepted_by_id, lab.request.accepted_at) == approval
    assert list(lab.request.items.order_by("pk").values()) == before_lines
    assert HardwareRequest.objects.filter(pk=other.pk).values().get() == before_other
    assert list(InventoryAsset.objects.order_by("pk").values()) == before_assets
    for model, rows in retained.items():
        assert list(model.objects.order_by("pk").values()) == rows
    event = AuditLog.objects.get(action="request.cancelled")
    assert event.meta == {"reason_recorded": True, "previous_box_id": box.pk}
    assert type(event.meta["previous_box_id"]) is int


def test_every_nonaccepted_state_refuses_without_effects():
    lab = accepted_lab()
    # Valid legacy DB state, deliberately inconsistent with its reservation. State
    # admission must reject before trying to interpret or repair those buckets.
    for state in ("draft", "pending_approval", "rejected", "issued",
                  "partially_returned", "returned", "closed_with_issue"):
        HardwareRequest.objects.filter(pk=lab.request.pk).update(status=state)
        refused(lab)


@pytest.mark.parametrize("trace", [
    "issued_quantity", "returned_quantity", "damaged_quantity", "missing_quantity",
    "needs_fix_quantity", "issued_at", "issued_by", "issue_evidence",
    "return_event", "accountability", "asset_link", "public_loan",
])
def test_any_handover_trace_refuses_even_with_zeroed_other_counters(trace):
    lab = accepted_lab(tracking="individual" if trace == "asset_link" else "quantity")
    assignment(lab)
    item = lab.request.items.get()
    # These are permitted DB rows modeling imported/legacy corruption, not a new
    # workflow: normal handover would set several traces together. Never bypass a
    # constraint or delete immutable evidence to manufacture the fixture.
    if trace.endswith("_quantity"):
        HardwareRequestItem.objects.filter(pk=item.pk).update(**{trace: 1})
    elif trace in {"issued_at", "issued_by", "issue_evidence"}:
        value = timezone.now() if trace == "issued_at" else (
            lab.actor if trace == "issued_by" else photo(lab))
        setattr(lab.request, trace, value)
        lab.request.save(update_fields=[trace])
    elif trace == "return_event":
        ReturnEvent.objects.create(request=lab.request, makerspace=lab.space,
            evidence=photo(lab, "return"), remark="Legacy return", actor=lab.actor)
    elif trace == "accountability":
        RequesterAccountability.objects.create(request=lab.request, request_item=item,
            makerspace=lab.space, requester=lab.request.requester, issue_type="missing",
            quantity=1, created_by=lab.actor)
    elif trace == "asset_link":
        # Keep physical/bucket stock valid: the link itself must cause refusal,
        # independently of the quantity-with-assets ambiguity guard.
        HardwareRequestItemAsset.objects.create(request_item=item, asset=lab.assets[0], outcome="returned")
    else:
        PublicToolLoan.objects.create(request=lab.request, makerspace=lab.space,
            requester=lab.request.requester, target_type="product", target_id=lab.product.pk,
            target_label="Legacy loan", status="returned")
    refused(lab)


@pytest.mark.parametrize("drift", ["pooled_shortage", "surplus", "foreign_request",
                                  "foreign_product", "foreign_asset", "quantity_assets",
                                  "individual_bucket", "foreign_box"])
def test_ambiguous_reservations_refuse_entire_transaction_without_repair(drift):
    lab = accepted_lab(tracking="individual" if drift in {"individual_bucket", "foreign_asset"} else "quantity")
    assignment(lab)
    if drift == "pooled_shortage":
        other = make_hardware_request(lab.space, lab.product, quantity=2)
        accept(lab.client, other)
        assert buckets(lab.product) == (4, 4, 0, 8)
        # A+B accepted two each, but the legacy pooled bucket can only cover B.
        InventoryProduct.objects.filter(pk=lab.product.pk).update(reserved_quantity=2,
                                                                 available_quantity=6)
    elif drift == "surplus":
        InventoryProduct.objects.filter(pk=lab.product.pk).update(reserved_quantity=3,
                                                                 available_quantity=5)
    elif drift == "foreign_request":
        other = make_hardware_request(lab.space, lab.product, quantity=1)
        accept(lab.client, other)
        HardwareRequest.objects.filter(pk=other.pk).update(makerspace=make_space("foreign-demand"))
    elif drift == "foreign_product":
        InventoryProduct.objects.filter(pk=lab.product.pk).update(makerspace=make_space("foreign-product"))
    elif drift == "foreign_asset":
        # Preserve exact physical counts so only the tenant-binding guard can
        # refuse; quantity-mode ambiguity must not mask a missing tenant check.
        InventoryAsset.objects.filter(pk=lab.assets[0].pk).update(makerspace=make_space("foreign-asset"))
    elif drift == "quantity_assets":
        InventoryAsset.objects.create(makerspace=lab.space, product=lab.product, asset_tag="legacy")
    elif drift == "individual_bucket":
        InventoryProduct.objects.filter(pk=lab.product.pk).update(available_quantity=5)
    else:
        box = Box.objects.create(makerspace=make_space("foreign-box"), label="foreign")
        HardwareRequest.objects.filter(pk=lab.request.pk).update(assigned_box=box)
    refused(lab)


def test_later_product_drift_rolls_back_assignment_and_all_earlier_products():
    lab = accepted_lab()
    # A second product is reserved by the same actual acceptance as the first;
    # changing its bucket afterward must not partially release the first product.
    product = make_product(lab.space, name="Second product")
    request = make_hardware_request(lab.space, lab.product, quantity=1)
    HardwareRequestItem.objects.create(request=request, product=product, requested_quantity=1)
    accept(lab.client, request)
    lab.request = request
    assignment(lab)
    InventoryProduct.objects.filter(pk=product.pk).update(reserved_quantity=2, available_quantity=3)
    refused(lab)


def test_duplicate_cancel_has_one_credit_and_one_event():
    lab = accepted_lab()
    assert cancel(lab).status_code == 200
    refused(lab)
    assert buckets(lab.product) == (8, 0, 0, 8)
    assert AuditLog.objects.filter(action="request.cancelled", target_id=str(lab.request.pk)).count() == 1


def test_audit_failure_rolls_back_reason_box_stock_and_callbacks(monkeypatch, django_capture_on_commit_callbacks):
    from apps.hardware_requests import workflow
    from apps.audit import services

    lab = accepted_lab()
    assignment(lab)
    before = snapshot()
    original = services.record

    def fail_cancel(actor, action, **kwargs):
        event = original(actor, action, **kwargs)
        if action == "request.cancelled":
            raise RuntimeError("Injected durable audit failure")
        return event

    monkeypatch.setattr(services, "record", fail_cancel)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        with pytest.raises(RuntimeError, match="durable audit failure"):
            workflow.cancel_request(lab.actor, lab.request, "Private rollback reason")
    assert callbacks == []
    assert snapshot() == before
