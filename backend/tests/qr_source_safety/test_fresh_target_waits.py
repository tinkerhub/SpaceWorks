"""Real source/target waits reload ownership and never resurrect moved/deleted rows."""
import pytest
from django.db import transaction

from apps.boxes.models import QrCode
from apps.inventory.models import InventoryAsset, InventoryProduct
from tests.box_parent_safety.pg_helpers import blocked_by, workers
from tests.qr_source_safety.http_helpers import closure_lab, empty_product, prepared
from tests.qr_source_safety.pg_helpers import (
    assert_shared, atomic_request, exclusive, source_wait, table_lock,
)
from tests.qr_source_safety.race_helpers import backend_pid
from tests.qr_source_safety.state_helpers import state
from tests.qr_target_safety_helpers import target

pytestmark = pytest.mark.django_db(transaction=True)


def relocate(obj, lab, mutation, other_product):
    query = type(obj).objects.filter(pk=obj.pk)
    if mutation == "deleted":
        query.delete()
    elif isinstance(obj, InventoryAsset):
        query.update(makerspace_id=lab.other.pk, product_id=other_product.pk)
    else:
        query.update(makerspace_id=lab.other.pk)


@pytest.mark.parametrize("kind", ["api-product", "api-asset", "api-scan", "api-resolve"])
@pytest.mark.parametrize("mutation", ["moved", "deleted"])
def test_target_ownership_fresh_after_source_n_wait(closure_lab, kind, mutation):
    lab = closure_lab
    case = prepared(lab, kind)
    other_product = empty_product(lab.other)
    with workers() as start:
        with exclusive(lab.home.pk) as owner:
            pending = start(atomic_request(case.call))
            source_wait(pending, owner, lab.home.pk)
            relocate(case.obj, lab, mutation, other_product)
            before = state()
        assert pending.finish().status_code == 404
    assert state() == before


@pytest.mark.parametrize("kind", ["api-product", "api-asset", "api-rebind", "native-rebind"])
@pytest.mark.parametrize("mutation", ["moved", "deleted"])
def test_target_ownership_fresh_after_product_or_asset_row_wait(closure_lab, kind, mutation):
    lab = closure_lab
    case = prepared(lab, kind)
    obj = case.destination if kind.endswith("rebind") else case.obj
    other_product = empty_product(lab.other)
    with workers() as start:
        with transaction.atomic():
            type(obj).objects.select_for_update().get(pk=obj.pk)
            pending = start(atomic_request(case.call))
            blocked_by(pending, backend_pid(), table_lock(obj._meta.db_table))
            assert_shared(pending.pid, lab.home.pk)
            relocate(obj, lab, mutation, other_product)
            before = state()
        assert pending.finish().status_code == 404
    assert state() == before


@pytest.mark.parametrize("kind", ["api-generate", "native-generate"])
@pytest.mark.parametrize("mutation", ["moved", "deleted"])
def test_generation_fresh_product_after_real_product_wait(closure_lab, kind, mutation):
    lab = closure_lab
    case = prepared(lab, kind)
    with workers() as start:
        with transaction.atomic():
            InventoryProduct.objects.select_for_update().get(pk=case.obj.pk)
            pending = start(atomic_request(case.call))
            blocked_by(pending, backend_pid(), table_lock(InventoryProduct._meta.db_table))
            assert_shared(pending.pid, lab.home.pk)
            relocate(case.obj, lab, mutation, None)
            before = state()
        response = pending.finish()
    assert response.status_code == 404
    assert state() == before


@pytest.mark.parametrize("mutation", ["moved", "deleted"])
def test_cross_asset_destination_product_fresh_after_real_product_wait(closure_lab, mutation):
    lab = closure_lab
    case = prepared(lab, "api-cross-asset")
    third = target(lab.other, "product")  # An unrelated row cannot substitute for the admitted PK.
    with workers() as start:
        with transaction.atomic():
            InventoryProduct.objects.select_for_update().get(pk=case.destination.pk)
            pending = start(atomic_request(case.call))
            blocked_by(pending, backend_pid(), table_lock(InventoryProduct._meta.db_table))
            for tenant in (lab.home, lab.other):
                assert_shared(pending.pid, tenant.pk)
            if mutation == "moved":
                InventoryProduct.objects.filter(pk=case.destination.pk).update(makerspace_id=lab.home.pk)
            else:
                InventoryProduct.objects.filter(pk=case.destination.pk).delete()
            before = state()
        assert pending.finish().status_code == 409
    assert state() == before
