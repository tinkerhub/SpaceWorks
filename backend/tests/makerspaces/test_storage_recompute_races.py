"""Real accepted image producers versus the whole-counter exclusive scan."""
import pytest

from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace
from apps.tenant_migration import source_gate
from tests.makerspaces.storage_recompute_support import (
    WAIT, await_lock, counter, image_request, jobs, locks, recompute, storage_case,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("field", ["logo_key", "cover_image_key"])
@pytest.mark.parametrize("operation", ["upload", "delete"])
def test_real_producer_drains_before_scan_and_loop_reloads_images(
    storage_case, jobs, field, operation,
):
    case = storage_case
    space, store = case.space, case.store
    other_field = "cover_image_key" if field == "logo_key" else "logo_key"
    base, base_size = case.staged(color="green")
    image_request(space, case.actor, field=other_field, key=base)
    key, size = case.staged(color="red")
    if operation == "delete":
        image_request(space, case.actor, field=field, key=key)
    entered, release, pause = jobs.pause()

    def before_put(params):
        if params["Key"] == key:
            pause()

    def before_delete(params):
        if any(row["Key"] == key for row in params["Delete"]["Objects"]):
            # This callback runs after the actual metadata commit, before debit release.
            assert getattr(Makerspace.objects.get(pk=space.pk), field) == ""
            assert counter(space) == base_size + size
            pause()

    store.before_put = before_put if operation == "upload" else None
    store.before_delete = before_delete if operation == "delete" else None
    producer = jobs.spawn(lambda: image_request(
        space, case.actor, field=field, key=key if operation == "upload" else None,
    ))
    assert entered.wait(WAIT)
    holder = await_lock(space.pk, "ShareLock", granted=True)
    command = jobs.spawn(lambda: recompute(space))
    waiter = await_lock(space.pk, "ExclusiveLock", granted=False, blocker=holder)
    assert waiter != holder and not command.done.is_set()
    release.set()
    producer.result()
    output = command.result()
    expected = base_size + (size if operation == "upload" else 0)
    assert counter(space) == expected
    fresh = Makerspace.objects.get(pk=space.pk)
    assert getattr(fresh, field) == (key if operation == "upload" else "")
    assert getattr(fresh, other_field) == base
    assert f"total={expected} bytes" in output
    assert (key in store.objects) == (operation == "upload")
    assert locks(space.pk) == []


@pytest.mark.parametrize("operation", ["upload", "delete"])
def test_scan_first_blocks_producer_before_effects_and_preserves_later_delta(
    storage_case, jobs, monkeypatch, operation,
):
    case = storage_case
    space, store = case.space, case.store
    base, base_size = case.staged(color="green")
    image_request(space, case.actor, field="cover_image_key", key=base)
    key, size = case.staged(color="red")
    if operation == "delete":
        image_request(space, case.actor, key=key)
    old_total = base_size + (size if operation == "delete" else 0)
    entered, release, pause = jobs.pause()
    original_head = store.head_object

    def head(**params):
        result = original_head(**params)
        if params["Key"] == base and not entered.is_set():
            pause()
        return result

    monkeypatch.setattr(store, "head_object", head)
    command = jobs.spawn(lambda: recompute(space))
    assert entered.wait(WAIT)
    holder = await_lock(space.pk, "ExclusiveLock", granted=True)
    before_calls, before_audits = list(store.calls), AuditLog.objects.count()
    producer = jobs.spawn(lambda: image_request(
        space, case.actor, key=key if operation == "upload" else None,
    ))
    await_lock(space.pk, "ShareLock", granted=False, blocker=holder)
    assert not producer.done.is_set()
    assert store.calls == before_calls, "Producer reached provider before source admission"
    assert AuditLog.objects.count() == before_audits
    assert counter(space) == old_total
    assert Makerspace.objects.get(pk=space.pk).logo_key == (key if operation == "delete" else "")
    release.set()
    output = command.result()
    producer.result()
    assert f"total={old_total} bytes" in output
    assert counter(space) == base_size + (size if operation == "upload" else 0)
    assert (key in store.objects) == (operation == "upload")
    assert locks(space.pk) == []


def test_other_tenant_producer_and_ordinary_read_progress_during_scan(
    storage_case, jobs, monkeypatch,
):
    from tests.tenant_migration.source_gate_helpers import make_space

    case = storage_case
    key, size = case.staged()
    image_request(case.space, case.actor, key=key)
    other = make_space("recompute-other")
    Makerspace.objects.filter(pk=other.pk).update(resource_limit_overrides={"storage": 100000})
    foreign_key, foreign_size = case.staged(other, "red")
    entered, release, pause = jobs.pause()
    head = case.store.head_object

    def paused_head(**params):
        result = head(**params)
        if params["Key"] == key and not entered.is_set():
            pause()
        return result

    monkeypatch.setattr(case.store, "head_object", paused_head)
    command = jobs.spawn(lambda: recompute(case.space))
    assert entered.wait(WAIT)
    await_lock(case.space.pk, "ExclusiveLock", granted=True)
    read = jobs.spawn(lambda: (counter(case.space), Makerspace.objects.get(pk=case.space.pk).logo_key))
    producer = jobs.spawn(lambda: image_request(other, case.actor, key=foreign_key))
    assert read.result() == (size, key)
    producer.result()
    assert counter(other) == foreign_size and foreign_key in case.store.objects
    assert not command.done.is_set()
    release.set()
    assert f"total={size} bytes" in command.result()
    assert counter(other) == foreign_size


def test_queued_real_migration_claim_holds_global_zero_before_tenant_without_inversion(
    storage_case, jobs, monkeypatch,
):
    from tests.makerspaces.storage_recompute_faults import instrument

    case = storage_case
    key, size = case.staged()
    image_request(case.space, case.actor, key=key)
    entered, release, pause = jobs.pause()
    head = case.store.head_object

    def paused_head(**params):
        result = head(**params)
        if not entered.is_set():
            pause()
        return result

    def update_observation(probe, _cursor):
        assert not any(row[0] == probe.raw.get_backend_pid() for row in locks(0))

    opened = instrument(monkeypatch, after_update=update_observation)
    monkeypatch.setattr(case.store, "head_object", paused_head)
    command = jobs.spawn(lambda: recompute(case.space))
    assert entered.wait(WAIT)
    holder = await_lock(case.space.pk, "ExclusiveLock", granted=True)
    migration = jobs.spawn(lambda: source_gate.claim(case.space, case.actor))
    waiter = await_lock(case.space.pk, "ExclusiveLock", granted=False, blocker=holder)
    assert waiter == migration.pid
    assert await_lock(0, "ExclusiveLock", granted=True) == waiter
    assert not migration.done.is_set()
    release.set()
    assert f"total={size} bytes" in command.result()
    lease = migration.result()
    assert lease.state == "draining" and counter(case.space) == size
    assert len(opened) == 1 and opened[0].raw.closed
    assert locks(case.space.pk) == [] and locks(0) == []
