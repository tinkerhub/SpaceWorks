"""Preserve labels/sorts, revoked eligibility, limits and real actor audit semantics."""
import pytest
from django.urls import reverse

from apps.boxes.models import QrCode
from apps.inventory.models import InventoryAsset
from apps.operations.models import QrPrintBatchItem
from tests.box_parent_safety.pg_helpers import workers
from tests.qr_print_race_safety.helpers import (
    add_http, assert_event, assert_order, events, item_write, lab, prepare, row, state,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("status", ["active", "revoked"])
@pytest.mark.parametrize("label", [None, "", "M" * 255], ids=["default", "blank", "explicit-max"])
def test_actual_http_label_sort_and_revoked_qr_positive_controls(lab, kind, status, label):
    case = prepare(lab, kind)
    if status == "revoked":
        case.qr.status = QrCode.Status.REVOKED
        case.qr.save(update_fields=["status", "updated_at"])
    qr_before = row(QrCode, case.qr.pk)
    data = {"sort_order": 13}
    if label is not None:
        data["label_text"] = label
    with workers() as start:
        api = start(lambda: add_http(lab, case, **data))
        response = api.finish()
    assert response.status_code == 201, response.data
    item = QrPrintBatchItem.objects.get(pk=response.data["id"])
    assert (item.label_text, item.sort_order, item.target_type, item.target_id) == (
        label or case.label, 13, kind, case.obj.pk,
    )
    assert_event(events().get(), lab, item, "qr_print_batch_item.created")
    assert_order(api, lab, case, wrote=True)
    assert row(QrCode, case.qr.pk) == qr_before


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("change", [
    {"label_text": "Changed"}, {"sort_order": 9}, {"label_text": "Changed", "sort_order": 9},
], ids=["label", "sort", "both"])
def test_changed_readd_updates_same_full_row_and_records_one_actual_actor_event(lab, kind, change):
    case = prepare(lab, kind)
    response = add_http(lab, case, label_text="Original", sort_order=3)
    assert response.status_code == 201, response.data
    item = QrPrintBatchItem.objects.get(pk=response.data["id"])
    original, qr_before = row(QrPrintBatchItem, item.pk), row(QrCode, case.qr.pk)
    before_ids = set(events().values_list("pk", flat=True))
    data = {"label_text": "Original", "sort_order": 3, **change}
    with workers() as start:
        api = start(lambda: add_http(lab, case, **data))
        response = api.finish()
    assert response.status_code == 201 and response.data == {"id": item.pk}
    assert row(QrPrintBatchItem, item.pk) == {**original, **change}
    assert QrPrintBatchItem.objects.count() == 1
    delta = events().exclude(pk__in=before_ids)
    assert delta.count() == 1
    assert_event(delta.get(), lab, item, "qr_print_batch_item.updated")
    assert len([s for s in api.statements if item_write(s)]) == 1
    assert_order(api, lab, case, wrote=True)
    assert row(QrCode, case.qr.pk) == qr_before


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("explicit_sort", [False, True], ids=["preserve-sort", "explicit-same-sort"])
def test_unchanged_readd_emits_no_audit_and_no_update(lab, kind, explicit_sort):
    case = prepare(lab, kind)
    original = add_http(lab, case, label_text="Unchanged", sort_order=7)
    assert original.status_code == 201, original.data
    before = state()
    data = {"label_text": "Unchanged", **({"sort_order": 7} if explicit_sort else {})}
    with workers() as start:
        api = start(lambda: add_http(lab, case, **data))
        response = api.finish()
    assert response.status_code == 201 and response.data == original.data
    assert_order(api, lab, case, wrote=False)
    assert not any(s.sql.startswith("UPDATE ") for s in api.statements)
    assert state() == before


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("existing", [False, True], ids=["create", "readd"])
@pytest.mark.parametrize("data,field,code", [
    ({"label_text": "L" * 256}, "label_text", "max_length"),
    ({"sort_order": -1}, "sort_order", "min_value"),
])
def test_actual_serializer_rejects_overlong_label_and_negative_sort_without_writes(
    lab, kind, existing, data, field, code,
):
    case = prepare(lab, kind)
    if existing:
        response = add_http(lab, case, label_text="Keep", sort_order=5)
        assert response.status_code == 201, response.data
    before = state()
    response = add_http(lab, case, **data)
    assert response.status_code == 400, response.data
    assert response.data[field][0].code == code
    assert state() == before


@pytest.mark.parametrize("field,limit", [("serial_numbers", 100), ("name_prefix", 154)])
@pytest.mark.parametrize("extra", [0, 1], ids=["limit-accepted", "over-limit-refused"])
def test_generation_http_preserves_explicit_serial_and_prefix_limits(lab, field, limit, extra):
    case = prepare(lab, "asset")
    product = case.obj.product
    # The stable target fixture already has one asset: generation adds a new unit
    # only after existing assets have active QR mappings (prepare supplies one).
    text = "Z" * (limit + extra)
    value = [text] if field == "serial_numbers" else text
    before = state()
    response = lab.api.post(
        reverse("asset-generate", args=[product.pk]),
        {"count": 1, "print_batch_id": lab.batch.pk, field: value}, format="json",
    )
    if extra:
        assert response.status_code == 400, response.data
        error = response.data[field][0]
        if field == "serial_numbers":
            error = error[0]
        assert error.code == "max_length"
        assert state() == before
    else:
        assert response.status_code == 201, response.data
        generated = InventoryAsset.objects.get(pk=response.data["assets"][0]["id"])
        assert generated.pk != case.obj.pk
        item = QrPrintBatchItem.objects.get(batch=lab.batch)
        if field == "serial_numbers":
            assert generated.serial_number == text
        else:
            assert item.label_text.startswith(text + " ")
        assert len(item.label_text) <= 255
