"""Actual commit, deletion and quota release stay within one tenant mutex."""
from threading import Barrier, Event
from unittest.mock import Mock

import pytest
from django.db import connection
from rest_framework.exceptions import ValidationError

from apps import object_storage_lifecycle as lifecycle
from apps.inventory import public_image_storage as storage
from apps.machines import services
from apps.machines.models import Machine
from apps.makerspaces import limits
from tests.atomic_publication.domain import bind_store, setup_machine
from tests.atomic_publication.store import error, png
from tests.atomic_publication.threading import workers

pytestmark = pytest.mark.django_db(transaction=True)


def test_detach_competing_reattach_cannot_pass_commit_cleanup_quota_boundary(monkeypatch):
    monkeypatch.setattr("apps.inventory.public_image_publication.time.sleep", lambda delay: None)
    space, actor, first = setup_machine("atomic-detach-reattach", monkeypatch)
    second = Machine.objects.create(makerspace=space, machine_type=first.machine_type, name="Second")
    store = bind_store(monkeypatch, storage)
    key, data = f"machine/{space.pk}/old.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    services.update_image(first, actor, key)
    space.resource_limit_overrides = {"storage": len(data)}
    space.save(update_fields=["resource_limit_overrides"])
    deleting, proceed, claiming = Event(), Event(), Event()
    factory = Mock(wraps=lifecycle._new_lock_connection)
    monkeypatch.setattr(lifecycle, "_new_lock_connection", factory)

    def pause_delete(kwargs):
        if not any(item["Key"] == key for item in kwargs["Delete"]["Objects"]):
            return
        assert not connection.in_atomic_block
        # Detachment has actually committed, not just released an inner savepoint.
        assert Machine.objects.get(pk=first.pk).image_key == ""
        space.refresh_from_db()
        assert space.storage_bytes_used == len(data)
        deleting.set()
        assert proceed.wait(4)
    store.before_delete = pause_delete
    with workers() as spawn:
        detach = spawn(lambda: services.remove_image(first, actor))
        assert deleting.wait(4)
        def reattach():
            claiming.set()
            try:
                return services.update_image(second, actor, key)
            except ValidationError:
                return None  # Missing retired bytes; caller must upload afresh.
        attach = spawn(reattach)
        try:
            assert claiming.wait(3)
            assert not attach.done()
        finally:
            proceed.set()
        detach.result(timeout=8)
        assert attach.result(timeout=8) is None
    space.refresh_from_db()
    assert space.storage_bytes_used == 0 and key not in store.objects
    assert factory.call_count == 2, "callback must reuse detach guard"
    store.before_delete = None
    store.seed(storage.staging_key(key), data, "image/png")
    services.update_image(second, actor, key)
    space.refresh_from_db()
    assert space.storage_bytes_used == len(data) and store.objects[key][0] == data


def test_failed_version_proof_cannot_credit_managed_quota(monkeypatch):
    space, actor, machine = setup_machine("atomic-cleanup-failed-proof", monkeypatch)
    store = bind_store(monkeypatch, storage)
    key, data = f"machine/{space.pk}/kept.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    services.update_image(machine, actor, key)
    store.list_object_versions = Mock(side_effect=error("NotImplemented", 501))
    services.remove_image(machine, actor)
    machine.refresh_from_db()
    space.refresh_from_db()
    assert machine.image_key == ""
    assert store.objects[key][0] == data and space.storage_bytes_used == len(data)


def test_opposite_image_swaps_finish_without_ordering_deadlock(monkeypatch):
    space, actor, first = setup_machine("atomic-opposite-swaps", monkeypatch)
    second = Machine.objects.create(makerspace=space, machine_type=first.machine_type, name="Second")
    store = bind_store(monkeypatch, storage)
    keys = [f"machine/{space.pk}/{name}.png" for name in ("first", "second")]
    data = png()
    for holder, key in zip((first, second), keys):
        store.seed(storage.staging_key(key), data, "image/png")
        services.update_image(holder, actor, key)
    start = Barrier(2)
    def swap(holder, key):
        start.wait(timeout=4)
        with pytest.raises(ValidationError):
            services.update_image(holder, actor, key)
    with workers() as spawn:
        a = spawn(lambda: swap(first, keys[1]))
        b = spawn(lambda: swap(second, keys[0]))
        a.result(timeout=10)
        b.result(timeout=10)
    first.refresh_from_db()
    second.refresh_from_db()
    space.refresh_from_db()
    assert [first.image_key, second.image_key] == keys
    assert space.storage_bytes_used == len(data) * 2
    assert all(key in store.objects for key in keys)


@pytest.mark.parametrize("schedule", ["release_public_image_on_commit", "delete_public_image_on_commit"])
def test_full_purge_skips_callback_before_unusable_guard_or_source_reentry(schedule, monkeypatch):
    space, _actor, _machine = setup_machine(f"atomic-purge-{schedule[:7]}", monkeypatch)
    guard = Mock()
    guard.verify.side_effect = AssertionError("full purge must not verify ordinary guard")
    monkeypatch.setattr("apps.makerspaces.purge_cleanup.owns_cleanup", lambda pk: pk == space.pk)
    callback = Mock(side_effect=AssertionError("full purge must not schedule callback"))
    monkeypatch.setattr(storage.transaction, "on_commit", callback)
    getattr(storage, schedule)(space, "old.png", guard=guard)
    callback.assert_not_called()
    guard.verify.assert_not_called()
