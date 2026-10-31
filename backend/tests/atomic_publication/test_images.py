"""Idempotency and competing canonical holders through production image services."""
from threading import Barrier

import pytest
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.bookings import storage as booking_storage
from apps.bookings.models import BookableSpace
from apps.inventory import public_image_storage as storage
from apps.machines import services
from apps.machines.models import Machine
from apps.makerspaces import profile_images
from apps.makerspaces.models import MakerspaceMembership, MemberProfile, MemberProject
from tests.atomic_publication.domain import bind_store, setup_machine
from tests.atomic_publication.store import png
from tests.atomic_publication.threading import workers
from tests.return_helpers import authenticated_client, make_member

pytestmark = pytest.mark.django_db(transaction=True)


def test_booking_same_key_repeated_finalize_preserves_image_quota_and_single_audit(monkeypatch):
    space, actor, _machine = setup_machine("atomic-booking-repeat", monkeypatch)
    target = BookableSpace.objects.create(makerspace=space, name="Studio")
    key = booking_storage.build_object_key(space.pk, target.pk, ".png")
    store = bind_store(monkeypatch, booking_storage)
    data = png()
    store.seed(booking_storage.staging_key(key), data, "image/png")
    client = authenticated_client(actor)
    url = reverse("admin-bookable-space-image-finalize", kwargs={"pk": target.pk})
    for _ in range(3):
        result = client.post(url, {"object_key": key}, format="json")
        assert result.status_code == 200, result.data
        assert store.objects[key][0] == data
        space.refresh_from_db()
        assert space.storage_bytes_used == len(data)
    target.refresh_from_db()
    assert target.image_key == key
    assert AuditLog.objects.filter(makerspace=space, action="booking.space_image_updated").count() == 1
    assert len(store.put_bodies) == 1
    assert not any(item["Key"] == key for op, kw in store.calls if op == "delete" for item in kw["Delete"]["Objects"])


def test_machine_concurrent_stale_holder_same_key_charges_once(monkeypatch):
    space, actor, machine = setup_machine("atomic-machine-repeat", monkeypatch)
    store = bind_store(monkeypatch, storage)
    key, data = f"machine/{space.pk}/same.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    start = Barrier(2)
    def finalize():
        stale = Machine.objects.get(pk=machine.pk)
        start.wait(timeout=4)
        return services.update_image(stale, actor, key).pk
    with workers() as spawn:
        first, second = spawn(finalize), spawn(finalize)
        assert first.result(timeout=10) == second.result(timeout=10) == machine.pk
    services.update_image(machine, actor, key)
    space.refresh_from_db()
    machine.refresh_from_db()
    assert machine.image_key == key and space.storage_bytes_used == len(data)
    assert store.objects[key][0] == data
    assert len(store.put_bodies) == 1
    assert AuditLog.objects.filter(makerspace=space, action="machine.image_updated").count() == 1


def test_two_machine_holders_cannot_claim_same_key(monkeypatch):
    space, actor, machine = setup_machine("atomic-machine-claim", monkeypatch)
    other = Machine.objects.create(makerspace=space, machine_type=machine.machine_type, name="Other")
    store = bind_store(monkeypatch, storage)
    key, data = f"machine/{space.pk}/shared.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    start = Barrier(2)
    def claim(holder):
        start.wait(timeout=4)
        try:
            return services.update_image(holder, actor, key).pk
        except ValidationError:
            return None
    with workers() as spawn:
        a, b = spawn(lambda: claim(machine)), spawn(lambda: claim(other))
        accepted = [value for value in (a.result(timeout=10), b.result(timeout=10)) if value is not None]
    assert len(accepted) == 1
    assert Machine.objects.filter(makerspace=space, image_key=key).count() == 1
    space.refresh_from_db()
    assert space.storage_bytes_used == len(data) and store.objects[key][0] == data


@pytest.mark.parametrize("other_holder", ["same-profile-project", "different-profile"])
def test_member_avatar_key_cannot_be_shared_with_another_holder(other_holder, monkeypatch):
    space, actor, _machine = setup_machine(f"atomic-member-{other_holder}", monkeypatch)
    profile = MemberProfile.objects.create(membership=MakerspaceMembership.objects.get(user=actor, makerspace=space))
    store = bind_store(monkeypatch, storage)
    key, data = f"member/{space.pk}/avatar.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    profile_images.set_avatar(profile, key)
    if other_holder == "different-profile":
        user = make_member("atomic-other-profile", space)
        other = MemberProfile.objects.create(membership=MakerspaceMembership.objects.get(user=user, makerspace=space))
        operation = lambda: profile_images.set_avatar(other, key)
    else:
        project = MemberProject.objects.create(profile=profile, title="Project")
        operation = lambda: profile_images.set_project_image(profile, project, key)
    with pytest.raises(ValidationError):
        operation()
    space.refresh_from_db()
    profile.refresh_from_db()
    assert profile.avatar_key == key and space.storage_bytes_used == len(data)
    assert store.objects[key][0] == data


def test_machine_metadata_failure_keeps_accepted_other_holder_bytes(monkeypatch):
    space, actor, machine = setup_machine("atomic-image-metadata-failure", monkeypatch)
    store = bind_store(monkeypatch, storage)
    key, data = f"machine/{space.pk}/accepted.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    services.update_image(machine, actor, key)
    second = Machine.objects.create(makerspace=space, machine_type=machine.machine_type, name="Other")
    with pytest.raises(ValidationError):
        services.update_image(second, actor, key)
    assert store.objects[key][0] == data
    space.refresh_from_db()
    assert space.storage_bytes_used == len(data)


def test_image_audit_failure_rolls_back_holder_and_quota_without_deleting_either_final(monkeypatch):
    space, actor, machine = setup_machine("atomic-image-audit-failure", monkeypatch)
    store = bind_store(monkeypatch, storage)
    old, new = [f"machine/{space.pk}/{name}.png" for name in ("old", "new")]
    old_data, new_data = png("blue"), png("red")
    store.seed(storage.staging_key(old), old_data, "image/png")
    services.update_image(machine, actor, old)
    store.seed(storage.staging_key(new), new_data, "image/png")
    def failed_audit(*args, **kwargs):
        raise RuntimeError("audit write refused")
    monkeypatch.setattr(services, "record", failed_audit)
    with pytest.raises(RuntimeError, match="audit write refused"):
        services.update_image(machine, actor, new)
    machine.refresh_from_db()
    space.refresh_from_db()
    assert machine.image_key == old and space.storage_bytes_used == len(old_data)
    assert store.objects[old][0] == old_data and store.objects[new][0] == new_data
    assert AuditLog.objects.filter(makerspace=space, action="machine.image_updated").count() == 1


def test_invalid_public_image_loser_holds_guard_and_cannot_cleanup_winner(monkeypatch):
    from threading import Event
    space, actor, machine = setup_machine("atomic-invalid-image-loser", monkeypatch)
    store = bind_store(monkeypatch, storage)
    key, data = f"machine/{space.pk}/winner.png", png()
    staging = storage.staging_key(key)
    store.seed(staging, b"bad PNG", "image/png")
    read, proceed, winner_started, winner_done = Event(), Event(), Event(), Event()
    original_get = store.get_object
    paused = False
    def paused_invalid_get(**kwargs):
        nonlocal paused
        result = original_get(**kwargs)
        if kwargs["Key"] == staging and not paused:
            paused = True
            read.set()
            assert proceed.wait(4)
        return result
    store.get_object = paused_invalid_get
    def invalid():
        with pytest.raises(ValidationError):
            services.update_image(machine, actor, key)
    def valid():
        winner_started.set()
        try:
            return services.update_image(machine, actor, key)
        finally:
            winner_done.set()
    with workers() as spawn:
        loser = spawn(invalid)
        assert read.wait(4)
        winner = spawn(valid)
        try:
            assert winner_started.wait(3)
            assert not winner_done.wait(0.15)
            store.seed(staging, data, "image/png")
        finally:
            proceed.set()
        loser.result(timeout=8)
        winner.result(timeout=8)
    machine.refresh_from_db()
    space.refresh_from_db()
    assert machine.image_key == key and store.objects[key][0] == data
    assert space.storage_bytes_used == len(data)
    assert AuditLog.objects.filter(makerspace=space, action="machine.image_updated").count() == 1
