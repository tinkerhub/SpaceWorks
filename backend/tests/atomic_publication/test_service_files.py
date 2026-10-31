"""Attachment races exercise real finalization and real tenant exclusion."""
from threading import Event

import pytest
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.evidence.storage import StorageUnavailable
from apps.machines import service_storage as storage
from apps.machines.models import ServiceRequestFile
from apps.object_storage_lifecycle import storage_lifecycle, StorageGuard
from tests.atomic_publication.domain import bind_store, service_file
from tests.atomic_publication.threading import workers

pytestmark = pytest.mark.django_db(transaction=True)
DATA = b"%PDF-1.7\naccepted immutable document"


def assert_accepted(space, row, file, store):
    file.refresh_from_db()
    space.refresh_from_db()
    assert file.service_request_id == row.pk and file.attached_at is not None
    assert (file.size_bytes, file.content_type) == (len(DATA), "application/pdf")
    assert space.storage_bytes_used == len(DATA)
    assert store.objects[file.object_key][0] == DATA
    assert AuditLog.objects.filter(makerspace=space, action="machine_service.file_attached").count() == 1
    file.size_bytes += 1
    with pytest.raises(RuntimeError, match="immutable"):
        file.save(update_fields=["size_bytes"])


def test_duplicate_concurrent_finalize_attaches_and_charges_exactly_once(monkeypatch):
    space, actor, _machine, row, file = service_file("atomic-file-duplicate", monkeypatch)
    store = bind_store(monkeypatch, storage)
    store.seed(storage.staging_key(file.object_key), DATA)
    publishing, proceed, second_started = Event(), Event(), Event()

    def pause(kwargs):
        publishing.set()
        assert proceed.wait(4)
    store.before_put = pause
    with workers() as spawn:
        first = spawn(lambda: storage.finalize_file(row, file_id=file.pk, actor=actor))
        assert publishing.wait(4)
        def duplicate():
            second_started.set()
            with pytest.raises(ValidationError):
                storage.finalize_file(row, file_id=file.pk, actor=actor)
        second = spawn(duplicate)
        try:
            assert second_started.wait(3)
            assert not second.done()
        finally:
            proceed.set()
        first.result(timeout=8)
        second.result(timeout=8)
    assert_accepted(space, row, file, store)
    assert len(store.put_bodies) == 1


def test_invalid_loser_excludes_winner_until_release_and_never_deletes_accepted_bytes(monkeypatch):
    space, actor, _machine, row, file = service_file("atomic-file-invalid-loser", monkeypatch)
    store = bind_store(monkeypatch, storage)
    staging = storage.staging_key(file.object_key)
    store.seed(staging, b"not PDF")
    read, resume, winner_started, winner_done = Event(), Event(), Event(), Event()
    original_get = store.get_object
    paused = False

    def pause_invalid_snapshot(**kwargs):
        nonlocal paused
        response = original_get(**kwargs)
        if kwargs["Key"] == staging and not paused:
            paused = True
            read.set()
            assert resume.wait(4)
        return response
    store.get_object = pause_invalid_snapshot
    with workers() as spawn:
        def invalid():
            with pytest.raises(ValidationError):
                storage.finalize_file(row, file_id=file.pk, actor=actor)
        loser = spawn(invalid)
        assert read.wait(4)
        def accept_winner():
            winner_started.set()
            try:
                return storage.finalize_file(row, file_id=file.pk, actor=actor)
            finally:
                winner_done.set()
        winner = spawn(accept_winner)
        try:
            assert winner_started.wait(3)
            assert not winner_done.wait(0.15)
            store.seed(staging, DATA)
        finally:
            resume.set()
        loser.result(timeout=8)
        winner.result(timeout=8)
    assert_accepted(space, row, file, store)
    with pytest.raises(ValidationError):
        storage.finalize_file(row, file_id=file.pk, actor=actor)
    assert store.objects[file.object_key][0] == DATA


@pytest.mark.parametrize("first_action", ["delete", "finalize"])
def test_staged_delete_vs_finalize_has_one_non_dangling_winner(first_action, monkeypatch):
    space, actor, _machine, row, file = service_file(f"atomic-file-{first_action}", monkeypatch)
    store = bind_store(monkeypatch, storage)
    store.seed(storage.staging_key(file.object_key), DATA)
    started = Event()
    with workers() as spawn:
        with storage_lifecycle(space.pk) as guard:
            def competing():
                started.set()
                try:
                    if first_action == "delete":
                        storage.finalize_file(row, file_id=file.pk, actor=actor)
                    else:
                        storage.delete_staged_file(file, actor=actor)
                except ValidationError:
                    return "rejected"
                pytest.fail("competing mutation accepted")
            competitor = spawn(competing)
            assert started.wait(3)
            if first_action == "delete":
                storage.delete_staged_file(file, actor=actor, guard=guard)
            else:
                storage.finalize_file(row, file_id=file.pk, actor=actor, guard=guard)
            assert not competitor.done()
        assert competitor.result(timeout=8) == "rejected"
    if first_action == "delete":
        assert not ServiceRequestFile.objects.filter(pk=file.pk).exists()
        assert file.object_key not in store.objects
        space.refresh_from_db()
        assert space.storage_bytes_used == 0
    else:
        assert_accepted(space, row, file, store)


def test_changed_owner_after_storage_preparation_rolls_back_without_final_compensation(monkeypatch):
    space, actor, _machine, row, file = service_file("atomic-file-owner", monkeypatch)
    store = bind_store(monkeypatch, storage)
    store.seed(storage.staging_key(file.object_key), DATA)
    def change_owner(kwargs):
        ServiceRequestFile.objects.filter(pk=file.pk).update(owner_user_id=actor.pk + 99999)
    store.before_put = change_owner
    with pytest.raises(ValidationError):
        storage.finalize_file(row, file_id=file.pk, actor=actor)
    file.refresh_from_db()
    space.refresh_from_db()
    assert file.service_request_id is None and space.storage_bytes_used == 0
    assert store.objects[file.object_key][0] == DATA
    assert not AuditLog.objects.filter(makerspace=space, action="machine_service.file_attached").exists()


def test_guard_loss_after_publication_prevents_metadata_acceptance_and_final_cleanup(monkeypatch):
    space, actor, _machine, row, file = service_file("atomic-file-guard-loss", monkeypatch)
    store = bind_store(monkeypatch, storage)
    store.seed(storage.staging_key(file.object_key), DATA)
    with storage_lifecycle(space.pk) as guard:
        store.before_put = lambda kwargs: guard.connection.rollback()
        with pytest.raises(StorageUnavailable):
            storage.finalize_file(row, file_id=file.pk, actor=actor, guard=guard)
    file.refresh_from_db()
    space.refresh_from_db()
    assert file.service_request_id is None and space.storage_bytes_used == 0
    assert store.objects[file.object_key][0] == DATA
    assert not AuditLog.objects.filter(makerspace=space, action="machine_service.file_attached").exists()


def test_guard_close_failure_after_commit_cannot_compensate_accepted_final(monkeypatch):
    space, actor, _machine, row, file = service_file("atomic-file-close-failure", monkeypatch)
    store = bind_store(monkeypatch, storage)
    store.seed(storage.staging_key(file.object_key), DATA)
    original_close = StorageGuard.close
    def fail_after_release(guard):
        original_close(guard)
        raise RuntimeError("close failed after committed attachment")
    monkeypatch.setattr(StorageGuard, "close", fail_after_release)
    with pytest.raises(StorageUnavailable):
        storage.finalize_file(row, file_id=file.pk, actor=actor)
    assert_accepted(space, row, file, store)


def test_service_attachment_preserves_pii_write_fence_before_metadata_acceptance(monkeypatch):
    from apps.encryption.write_fence import close_makerspace, reopen, PiiWriteFenced
    space, actor, _machine, row, file = service_file("atomic-file-pii-fence", monkeypatch)
    store = bind_store(monkeypatch, storage)
    store.seed(storage.staging_key(file.object_key), DATA)
    operation = close_makerspace(space.pk, "search_rotation", actor.pk)
    try:
        with pytest.raises(PiiWriteFenced):
            storage.finalize_file(row, file_id=file.pk, actor=actor)
        file.refresh_from_db()
        space.refresh_from_db()
        assert file.service_request_id is None and file.attached_at is None
        assert space.storage_bytes_used == 0
        assert store.objects[file.object_key][0] == DATA
        assert not AuditLog.objects.filter(makerspace=space, action="machine_service.file_attached").exists()
    finally:
        reopen(operation, actor.pk)
