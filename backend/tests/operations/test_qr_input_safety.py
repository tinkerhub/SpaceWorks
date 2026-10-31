"""OPS-S01: actual HTTP limits and persisted suffix-preserving derived text."""
from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.inventory.models import InventoryAsset
from apps.makerspaces import limits
from apps.operations.models import QrPrintBatch, QrPrintBatchItem
from apps.operations.services_qr_assets import add_qr_to_batch, generate_assets_with_qr
from tests.operations.qr_safety_helpers import (
    add_item, asset, batch, create_batch, generate, product, qr, qr_lab, state,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("field,size", [
    ("title", 200), ("label_text", 255), ("serial_numbers", 100), ("name_prefix", 154),
])
def test_api_accepts_exact_manual_limit_without_truncation(settings, field, size):
    lab = qr_lab(settings)
    item = product(lab)
    text = "X" * size
    if field == "title":
        response = create_batch(lab, text)
        assert response.status_code == 201, response.data
        assert QrPrintBatch.objects.get(pk=response.data["id"]).title == text
    elif field == "label_text":
        labels, code = batch(lab), qr(lab, item)
        response = add_item(lab, labels, code, label_text=text)
        assert response.status_code == 201, response.data
        assert QrPrintBatchItem.objects.get(pk=response.data["id"]).label_text == text
    else:
        value = [text] if field == "serial_numbers" else text
        response = generate(lab, item, create_print_batch=True, **{field: value})
        assert response.status_code == 201, response.data
        unit = InventoryAsset.objects.get(pk=response.data["assets"][0]["id"])
        if field == "serial_numbers":
            assert unit.serial_number == text
        else:
            assert unit.notes == f"{text} #1"
            assert QrPrintBatchItem.objects.get(batch_id=response.data["print_batch_id"]).label_text == f"{text} 1"


@pytest.mark.parametrize("field,size", [
    ("title", 201), ("label_text", 256), ("serial_numbers", 101), ("name_prefix", 155),
])
def test_api_rejects_one_over_before_any_mutation_or_quota_check(settings, field, size):
    lab = qr_lab(settings)
    item = product(lab)
    labels, code = batch(lab), qr(lab, item)
    before = state()
    with patch.object(limits, "check_quota", wraps=limits.check_quota) as quota:
        if field == "title":
            response = create_batch(lab, "X" * size)
        elif field == "label_text":
            response = add_item(lab, labels, code, label_text="X" * size)
        else:
            value = ["X" * size] if field == "serial_numbers" else "X" * size
            response = generate(lab, item, create_print_batch=True, **{field: value})
        assert response.status_code == 400, response.data
        errors = response.data[field]
        error = errors[0][0] if field == "serial_numbers" else errors[0]
        assert error.code == "max_length"
        quota.assert_not_called()
    assert state() == before


@pytest.mark.parametrize("field,size", [("label_text", 256), ("name_prefix", 155), ("serial_numbers", 101)])
def test_service_also_refuses_oversized_explicit_input_without_truncation(settings, field, size):
    lab = qr_lab(settings)
    item = product(lab)
    labels, code = batch(lab), qr(lab, item)
    before = state()
    with patch.object(limits, "check_quota", wraps=limits.check_quota) as quota:
        with pytest.raises(ValidationError) as error:
            if field == "label_text":
                add_qr_to_batch(lab.actor, labels, code, label_text="X" * size)
            else:
                value = ["X" * size] if field == "serial_numbers" else "X" * size
                generate_assets_with_qr(lab.actor, item, {"count": 1, "create_print_batch": True, field: value})
        assert field in error.value.detail
        quota.assert_not_called()
    assert state() == before


@pytest.mark.parametrize("preexisting", [False, True], ids=["new-number", "existing-full-tag"])
@pytest.mark.parametrize("prefix", [None, ""], ids=["omitted-prefix", "empty-prefix"])
def test_long_product_generation_bounds_title_and_preserves_complete_suffix(settings, preexisting, prefix):
    lab = qr_lab(settings)
    item = product(lab, name="N" * 200)
    unit = asset(item, "T" * 100) if preexisting else None
    options = {} if prefix is None else {"name_prefix": prefix}

    response = generate(lab, item, create_print_batch=True, **options)

    assert response.status_code == 201, response.data
    labels = QrPrintBatch.objects.get(pk=response.data["print_batch_id"])
    assert labels.title == "N" * 185 + " unit QR labels"
    assert len(labels.title) == 200
    stored = labels.items.get()
    if preexisting:
        assert response.data["assets"][0]["id"] == unit.pk
        assert stored.label_text == "N" * 154 + " " + "T" * 100
        assert len(stored.label_text) == 255
        assert InventoryAsset.objects.get(pk=unit.pk).asset_tag == "T" * 100
    else:
        assert stored.label_text == "N" * 200 + " 1"
    assert stored.target_id == response.data["assets"][0]["id"]
    item.refresh_from_db()
    assert item.assets.count() == item.total_quantity == item.available_quantity == 1


def test_maximum_explicit_prefix_and_existing_full_tag_fit_exactly(settings):
    lab = qr_lab(settings)
    item = product(lab)
    unit = asset(item, "Z" * 100)

    response = generate(lab, item, name_prefix="P" * 154, create_print_batch=True)

    assert response.status_code == 201, response.data
    stored = QrPrintBatchItem.objects.get(batch_id=response.data["print_batch_id"])
    assert stored.target_id == unit.pk
    assert stored.label_text == "P" * 154 + " " + "Z" * 100
    assert len(stored.label_text) == 255


@pytest.mark.parametrize("unit_target", [False, True], ids=["product", "asset-full-tag"])
@pytest.mark.parametrize("label", [None, ""], ids=["omitted-label", "empty-label"])
def test_fallback_label_is_bounded_and_keeps_the_full_asset_identifier(settings, unit_target, label):
    lab = qr_lab(settings)
    item = product(lab, name="N" * 200)
    target = asset(item, "T" * 100) if unit_target else item
    code, labels = qr(lab, target), batch(lab)
    data = {} if label is None else {"label_text": label}

    response = add_item(lab, labels, code, **data)

    assert response.status_code == 201, response.data
    stored = QrPrintBatchItem.objects.get(pk=response.data["id"])
    assert stored.label_text == ("N" * 152 + " - " + "T" * 100 if unit_target else "N" * 200)
    assert len(stored.label_text) <= 255
    assert (stored.target_type, stored.target_id) == (code.target_type, target.pk)
