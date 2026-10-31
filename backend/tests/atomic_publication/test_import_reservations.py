"""Unscoped import target journals conservatively fence ordinary cleanup."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.inventory import tenant_object_callbacks
from apps.object_storage_lifecycle import storage_lifecycle
from apps.object_storage_references import key_in_use
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from apps.inventory import public_image_storage as storage
from tests.atomic_publication.domain import bind_store, setup_machine
from tests.atomic_publication.store import png

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("state", ["staged", "promoted", "failed", "rolled_back"])
def test_import_target_key_reservation_without_target_tenant_blocks_delete_and_quota_credit(state, monkeypatch):
    space, _actor, _machine = setup_machine("atomic-import-reservation", monkeypatch)
    store = bind_store(monkeypatch, storage)
    key, data = f"machine/{space.pk}/imported.png", png()
    store.seed(key, data, "image/png")
    space.storage_bytes_used = len(data)
    space.save(update_fields=["storage_bytes_used"])
    job = TenantImportJob.objects.create(source_archive_digest="a" * 64, target_makerspace=None,
                                         expires_at=timezone.now() + timedelta(days=1))
    TenantImportObject.objects.create(job=job, bucket_kind="public_image", source_key="source/key",
                                      staging_key="migration/staged", target_key=key, size=len(data),
                                      sha256="b" * 64, state=state)
    assert key_in_use("public_image", key) is True
    assert key_in_use("private", key) is False
    with storage_lifecycle(space.pk) as guard:
        tenant_object_callbacks.release_public_image(space, key, storage, guard=guard)
    space.refresh_from_db()
    assert store.calls == [] and store.objects[key][0] == data
    assert space.storage_bytes_used == len(data)
