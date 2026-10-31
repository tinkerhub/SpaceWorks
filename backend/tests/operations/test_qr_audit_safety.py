"""OPS-S02: persisted audit attribution, meaningful updates and atomic refusal."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.audit import services as audit
from apps.boxes.models import QrCode
from apps.operations.models import QrPrintBatchItem
from apps.operations.services_qr_assets import mark_batch_printed
from tests.operations.qr_safety_helpers import (
    add_item, assert_event, asset, audit_ids, batch, create_batch, generate,
    item_updates, new_events, product, qr, qr_lab, state,
)

pytestmark = pytest.mark.django_db


def test_new_asset_qr_has_exactly_one_attributed_event_and_reprint_is_idempotent(settings):
    lab = qr_lab(settings)
    unit = asset(product(lab))
    before = audit_ids()

    response = lab.client.post(f"/api/v1/admin/assets/{unit.pk}/qr", {}, format="json")

    assert response.status_code == 201, response.data
    code = QrCode.objects.get(pk=response.data["id"])
    assert (code.makerspace_id, code.target_type, code.target_id, code.created_by_id) == (
        lab.home.pk, QrCode.TargetType.ASSET, unit.pk, lab.actor.pk,
    )
    assert new_events(before).count() == 1
    event = new_events(before).get()
    assert_event(event, lab, "qr.created", code)
    assert event.meta == {}
    after_first = state()

    reprinted = lab.client.post(f"/api/v1/admin/assets/{unit.pk}/qr", {}, format="json")

    assert reprinted.status_code == 201, reprinted.data
    assert reprinted.data == response.data
    assert state() == after_first
    assert new_events(before).count() == 1


def test_batch_item_creation_is_audited_once_and_omitted_sort_noop_does_not_save(settings):
    lab = qr_lab(settings)
    target = product(lab)
    code, labels = qr(lab, target), batch(lab)
    before = audit_ids()

    response = add_item(lab, labels, code, label_text="Bench drill", sort_order=7)

    assert response.status_code == 201, response.data
    stored = QrPrintBatchItem.objects.get(pk=response.data["id"])
    assert (stored.batch_id, stored.qr_code_id, stored.label_text, stored.sort_order) == (
        labels.pk, code.pk, "Bench drill", 7,
    )
    assert (stored.target_type, stored.target_id) == (code.target_type, target.pk)
    assert new_events(before).count() == 1
    assert_event(new_events(before).get(), lab, "qr_print_batch_item.created", stored)
    assert new_events(before).get().meta == {}
    after_create = state()

    # An omitted sort order must preserve 7, rather than replacing it with count().
    with CaptureQueriesContext(connection) as queries:
        unchanged = add_item(lab, labels, code, label_text="Bench drill")

    assert unchanged.status_code == 201, unchanged.data
    assert unchanged.data == response.data
    assert item_updates(queries) == []
    assert state() == after_create


@pytest.mark.parametrize("change", [{"label_text": "Revised"}, {"sort_order": 9}], ids=["label", "sort"])
def test_only_actual_item_change_saves_once_and_emits_one_update(settings, change):
    lab = qr_lab(settings)
    code, labels = qr(lab, product(lab)), batch(lab)
    created = add_item(lab, labels, code, label_text="Original", sort_order=3)
    assert created.status_code == 201, created.data
    stored = QrPrintBatchItem.objects.get(pk=created.data["id"])
    before = audit_ids()
    payload = {"label_text": "Original", "sort_order": 3, **change}

    with CaptureQueriesContext(connection) as queries:
        updated = add_item(lab, labels, code, **payload)

    assert updated.status_code == 201, updated.data
    assert updated.data == created.data
    assert len(item_updates(queries)) == 1
    stored.refresh_from_db()
    assert stored.label_text == payload["label_text"] and stored.sort_order == payload["sort_order"]
    assert (stored.target_type, stored.target_id) == (code.target_type, code.target_id)
    assert new_events(before).count() == 1
    assert_event(new_events(before).get(), lab, "qr_print_batch_item.updated", stored)
    assert new_events(before).get().meta == {}
    after_update = state()

    with CaptureQueriesContext(connection) as queries:
        repeated = add_item(lab, labels, code, **payload)

    assert repeated.status_code == 201, repeated.data
    assert repeated.data == created.data
    assert item_updates(queries) == []
    assert state() == after_update


@pytest.mark.parametrize("preexisting", [False, True], ids=["new-units", "existing-units"])
def test_generation_keeps_aggregate_and_each_item_creation_audit(settings, preexisting):
    lab = qr_lab(settings)
    target = product(lab)
    if preexisting:
        asset(target, "EXISTING-A")
        asset(target, "EXISTING-B")
    before = audit_ids()

    response = generate(lab, target, count=2, create_print_batch=True)

    assert response.status_code == 201, response.data
    items = list(QrPrintBatchItem.objects.filter(batch_id=response.data["print_batch_id"]))
    assert len(items) == 2
    assert {item.target_id for item in items} == {row["id"] for row in response.data["assets"]}
    events = new_events(before)
    assert events.count() == 3
    aggregate = events.get(action="asset_units.generated")
    assert_event(aggregate, lab, "asset_units.generated", target)
    assert aggregate.meta == {"count": 2}
    for item in items:
        event = events.get(action="qr_print_batch_item.created", target_id=str(item.pk))
        assert_event(event, lab, "qr_print_batch_item.created", item)
        assert event.meta == {}


@pytest.mark.parametrize("operation,refused_action", [
    ("asset-qr", "qr.created"),
    ("item-create", "qr_print_batch_item.created"),
    ("item-update", "qr_print_batch_item.updated"),
    ("generate-item", "qr_print_batch_item.created"),
    ("generate-aggregate", "asset_units.generated"),
    ("print", "qr_print_batch.printed"),
    ("batch-create", "qr_print_batch.created"),
])
def test_audit_failure_rolls_back_source_rows_and_audit_rows(settings, monkeypatch, operation, refused_action):
    lab = qr_lab(settings)
    target = product(lab)
    unit = asset(target) if operation == "asset-qr" else None
    labels, code = batch(lab), qr(lab, target)
    if operation == "item-update":
        created = add_item(lab, labels, code, label_text="Original", sort_order=3)
        assert created.status_code == 201, created.data
    before = state()
    real_record = audit.record
    refused = []

    def record_then_refuse(actor, action, **kwargs):
        event = real_record(actor, action, **kwargs)
        if action == refused_action:
            refused.append(event.pk)
            raise RuntimeError("audit persistence refused")
        return event

    monkeypatch.setattr(audit, "record", record_then_refuse)
    with pytest.raises(RuntimeError, match="audit persistence refused"):
        if operation == "asset-qr":
            lab.client.post(f"/api/v1/admin/assets/{unit.pk}/qr", {}, format="json")
        elif operation in {"item-create", "item-update"}:
            add_item(lab, labels, code, label_text="Changed", sort_order=9)
        elif operation.startswith("generate-"):
            generate(lab, target, count=2, create_print_batch=True)
        elif operation == "print":
            mark_batch_printed(lab.actor, labels)
        else:
            create_batch(lab, "Rollback labels")

    assert len(refused) == 1  # The real audit insert was reached inside the mutation.
    assert state() == before
