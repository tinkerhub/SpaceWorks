"""Real batch image publication stays outside the batch transaction."""
import pytest

from apps.admin_api.bulk_import_apply import apply_import
from apps.inventory import public_image_storage as storage
from apps.inventory.models import InventoryProduct
from tests.atomic_publication.domain import bind_store, setup_machine
from tests.atomic_publication.store import png

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("allow_partial", [False, True])
@pytest.mark.parametrize("broken", [False, True])
def test_bulk_images_prepare_before_sql_and_preserve_batch_partial_policy(allow_partial, broken, monkeypatch):
    space, actor, _machine = setup_machine("atomic-bulk-preparation", monkeypatch)
    store = bind_store(monkeypatch, storage)
    data = png()
    keys = [f"items/{space.pk}/{index}.png" for index in range(2)]
    for index, key in enumerate(keys):
        store.seed(storage.staging_key(key), b"broken" if broken and index == 1 else data, "image/png")
    rows = [{"name": name, "total_quantity": "1", "available_quantity": "1", "image_key": key}
            for name, key in zip(("Good", "Second"), keys)]
    result = apply_import(actor, space, rows, {}, allow_partial=allow_partial)
    space.refresh_from_db()
    products = InventoryProduct.objects.filter(makerspace=space)
    # Image errors were row-level runtime failures before preparation moved out of SQL;
    # allow_partial governs parser-preview errors, not this later storage phase.
    expected = 1 if broken else 2
    assert result["applied"] is True and result["created"] == expected
    assert result["partial"] is broken
    assert products.count() == expected and space.storage_bytes_used == expected * len(data)
    assert products.get(name="Good").image_key == keys[0]
    assert store.objects[keys[0]][0] == data
    assert len(store.put_bodies) == (1 if broken else 2)


def test_bulk_rechecks_image_owner_after_preparation_before_accepting_row(monkeypatch):
    space, actor, machine = setup_machine("atomic-bulk-owner", monkeypatch)
    store = bind_store(monkeypatch, storage)
    key, data = f"items/{space.pk}/claimed.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    def imported_owner(kwargs):
        if kwargs["Key"] == key and key in store.objects:
            type(machine).objects.filter(pk=machine.pk).update(image_key=key)
    store.before_get = imported_owner
    result = apply_import(actor, space, [{"name": "Rejected", "total_quantity": "1", "available_quantity": "1", "image_key": key}], {}, allow_partial=True)
    assert result["created"] == 0 and result["partial"] is True
    assert not InventoryProduct.objects.filter(makerspace=space).exists()
    assert store.objects[key][0] == data
    space.refresh_from_db()
    assert space.storage_bytes_used == 0
