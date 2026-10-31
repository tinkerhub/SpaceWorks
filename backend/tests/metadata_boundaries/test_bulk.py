"""Bulk metadata owns preview progress and composes with caller transactions."""
import pytest
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.admin_api.bulk_import_apply import apply_import
from apps.admin_api.models import BulkImportJob
from apps.audit.models import AuditLog
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage
from apps.inventory.models import Category, InventoryProduct
from apps.makerspaces import limits
from apps.tenant_migration.gate_runtime import assert_boundary_held
from tests.atomic_publication.domain import bind_store
from tests.atomic_publication.store import png
from tests.metadata_boundaries.helpers import (
    CallerRollback, assert_caller_rollback, bulk_case, no_storage, snapshot,
)

pytestmark = pytest.mark.django_db


def rows():
    return [
        {"name": "Lamp", "description": "New description", "total_quantity": "99", "available_quantity": "99", "image_key": "", "category": "Optics"},
        {"name": "Meter", "description": "New description", "total_quantity": "2", "available_quantity": "2", "image_key": "", "category": "Optics"},
    ]


def test_metadata_import_nested_atomic_preserves_images_stock_and_unmapped_tracking(no_storage):
    case = bulk_case()
    with transaction.atomic():
        result = apply_import(case.actor, case.space, rows(), {})
        assert result["applied"] and result["created"] == result["updated"] == 1
        case.product.refresh_from_db(); case.space.refresh_from_db()
        assert case.product.image_key == f"items/{case.space.pk}/existing.png"
        assert case.product.description == "New description"
        assert (case.product.total_quantity, case.product.available_quantity, case.product.issued_quantity) == (3, 2, 1)
        assert case.product.tracking_mode == "quantity"
        assert case.product.category.name == "Optics" and Category.objects.filter(makerspace=case.space, name="Optics").count() == 1
        assert case.space.storage_bytes_used == 231
        assert AuditLog.objects.get(makerspace=case.space, action="inventory.bulk_imported").meta == {"created": 1, "updated": 1}


def test_caller_rollback_removes_products_categories_progress_and_audits(no_storage):
    case = bulk_case("bulk-caller-rollback")
    job = BulkImportJob.objects.create(makerspace=case.space, actor=case.actor, mode="apply")
    def progress(done, total):
        assert_boundary_held(case.space.pk)
        BulkImportJob.objects.filter(pk=job.pk).update(processed_rows=done, total_rows=total)
    def check(result):
        assert result["created"] == 1 and result["updated"] == 1
        assert Category.objects.filter(makerspace=case.space, name="Optics").exists()
        job.refresh_from_db()
        assert job.processed_rows == job.total_rows == 2
    assert_caller_rollback(case.space, lambda: apply_import(case.actor, case.space, rows(), {}, progress_callback=progress), check)


def test_invalid_preview_return_and_progress_db_write_share_boundary_and_caller_rollback(no_storage):
    case = bulk_case("bulk-invalid-preview")
    job = BulkImportJob.objects.create(makerspace=case.space, actor=case.actor, mode="apply")
    original = snapshot(case.space)
    calls = []
    def progress(done, total):
        assert_boundary_held(case.space.pk)
        calls.append((done, total))
        BulkImportJob.objects.filter(pk=job.pk).update(processed_rows=done)
    with pytest.raises(CallerRollback), transaction.atomic():
        result = apply_import(case.actor, case.space, [{"name": "", "total_quantity": "invalid"}], {}, progress_callback=progress)
        assert result["applied"] is False and result["errors"]
        job.refresh_from_db()
        assert job.processed_rows == 1 and calls == [(1, 1)]
        raise CallerRollback
    assert snapshot(case.space) == original


@pytest.mark.parametrize("same_key", [False, True])
def test_any_nonempty_image_key_including_attached_key_refuses_outer_atomic(same_key, no_storage):
    case = bulk_case("bulk-image-presence")
    key = case.product.image_key if same_key else f"items/{case.space.pk}/replacement.png"
    original = snapshot(case.space)
    with transaction.atomic(), pytest.raises(StorageUnavailable):
        apply_import(case.actor, case.space, [{"name": case.product.name, "total_quantity": "3", "available_quantity": "2", "image_key": key}], {})
    assert snapshot(case.space) == original


def test_metadata_branch_enforces_product_quota_before_category_or_product_writes(no_storage, monkeypatch):
    from rest_framework.exceptions import ValidationError

    case = bulk_case("bulk-metadata-quota")
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    case.space.resource_limit_overrides = {"products": 1}
    case.space.save(update_fields=["resource_limit_overrides"])
    original = snapshot(case.space)
    with transaction.atomic(), pytest.raises(ValidationError, match="limit"):
        apply_import(case.actor, case.space, rows(), {})
    assert snapshot(case.space) == original


def test_metadata_tracking_rejection_remains_per_row_without_phantom_stock(no_storage):
    case = bulk_case("bulk-metadata-tracking")
    result = apply_import(case.actor, case.space, [
        {"name": "Phantom", "tracking_mode": "individual", "total_quantity": "2", "available_quantity": "2"},
        {"name": "Real", "tracking_mode": "individual", "total_quantity": "0", "available_quantity": "0"},
    ], {}, allow_partial=True)
    assert result["applied"] and result["partial"] and result["created"] == 1
    assert not InventoryProduct.objects.filter(makerspace=case.space, name="Phantom").exists()
    product = InventoryProduct.objects.get(makerspace=case.space, name="Real")
    assert product.tracking_mode == "individual" and product.total_quantity == product.available_quantity == 0


@pytest.mark.django_db(transaction=True)
def test_native_admin_valid_image_import_uses_actual_guard_and_versioned_provider(monkeypatch):
    case = bulk_case("bulk-native-image")
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    case.space.resource_limit_overrides = {"storage": 100000}
    case.space.save(update_fields=["resource_limit_overrides"])
    from tests.test_admin_custom_views import make_superadmin

    client = Client(); client.force_login(make_superadmin("metadata-native-super"))
    store = bind_store(monkeypatch, public_image_storage)
    key, data = f"items/{case.space.pk}/native.png", png()
    store.seed(public_image_storage.staging_key(key), data, "image/png")
    url = reverse("admin:inventory_inventoryproduct_bulk_import")
    content = f"name,total_quantity,available_quantity,image_key\nNative,1,1,{key}\n".encode()
    preview = client.post(url, {"makerspace": case.space.pk, "file": SimpleUploadedFile("items.csv", content, content_type="text/csv")})
    assert preview.status_code == 200
    response = client.post(url, {"apply": "1"})
    assert response.status_code == 302
    assert InventoryProduct.objects.get(makerspace=case.space, name="Native").image_key == key
    assert store.objects[key][0] == data and len(store.put_bodies) == 1
    case.space.refresh_from_db()
    assert case.space.storage_bytes_used == 231 + len(data)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("failure", ["storage-lock", "image-preparation"])
def test_native_admin_storage_refusal_returns_usable_form_without_writes(failure, monkeypatch):
    case = bulk_case("bulk-native-refusal")
    from tests.test_admin_custom_views import make_superadmin

    client = Client(); client.force_login(make_superadmin("metadata-refusal-super"))
    key = f"items/{case.space.pk}/refused.png"
    url = reverse("admin:inventory_inventoryproduct_bulk_import")
    content = f"name,total_quantity,available_quantity,image_key\nRefused,1,1,{key}\n".encode()
    assert client.post(url, {"makerspace": case.space.pk, "file": SimpleUploadedFile("items.csv", content, content_type="text/csv")}).status_code == 200
    target = ("apps.object_storage_lifecycle._new_lock_connection" if failure == "storage-lock" else
              "apps.admin_api.bulk_import_apply.finalize_product_image")
    def unavailable(*_args, **_kwargs):
        raise StorageUnavailable
    monkeypatch.setattr(target, unavailable)
    original = snapshot(case.space)
    response = client.post(url, {"apply": "1"})
    assert response.status_code == 200
    assert response.context["form"].non_field_errors() or response.context["preview"]["errors"]
    assert not InventoryProduct.objects.filter(makerspace=case.space, name="Refused").exists()
    # A handled preparation error may retain the batch's zero-row audit; all
    # inventory, categories, counters and existing image metadata remain intact.
    assert snapshot(case.space)[:-1] == original[:-1]
