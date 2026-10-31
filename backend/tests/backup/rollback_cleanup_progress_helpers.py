"""Real cleanup fixtures and private progress I/O under the production locks."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from apps.backup import rollback_cleanup_progress as progress
from apps.backup.models import RestoreRollbackObject
from apps.backup.operation_lock import deployment_operation_lock
from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.purge_storage import bucket_name
from apps.tenant_migration.gate_locks import unscoped_writer_shared_boundary
from tests.backup.rollback_cleanup_outcome_helpers import outcome_store, recovery
from tests.makerspaces.module_cleanup_support import (
    ModuleStore, actor, module_space, module_store, rollback,
)


@pytest.fixture
def cleanup_env(outcome_store, settings):
    recovery()
    directory = Path(settings.BACKUP_OPS_DIR)
    directory.mkdir(parents=True, mode=0o700)
    return directory / progress.CURSOR_NAME


@contextmanager
def progress_boundary():
    with deployment_operation_lock(blocking=False), unscoped_writer_shared_boundary():
        yield


def saved_cursor():
    with progress_boundary():
        return progress.read_cleanup_progress().last_id


def save_cursor(last_id):
    with progress_boundary():
        progress.write_cleanup_progress(progress.read_cleanup_progress(), last_id)


def additional_case(item, store, *, global_row=False):
    """Share an actual restore, avoiding restore_fixture's stage-unique username."""
    space = module_space(f"progress-{uuid4().hex}", storage_bytes_used=100)
    row = rollback(item.restore, None if global_row else space, "events", "private",
                   f"legacy/{uuid4().hex}", 7)
    bucket = bucket_name(row.bucket_kind)
    original = store.put(bucket, row.source_key, b"oldcopy")
    replacement = store.put(bucket, row.source_key, b"replacement")
    copies = {store.put(bucket, row.copy_key, b"oldcopy"),
              store.put(bucket, row.copy_key, b"", marker=True)}
    return SimpleNamespace(space=space, restore=item.restore, row=row, original=original,
                           replacement=replacement, copies=copies)


def assert_cleaned(item, store):
    assert not RestoreRollbackObject.objects.filter(pk=item.row.pk).exists()
    assert all(key not in store.objects for key in item.copies)
    assert store.objects[item.original] == (b"oldcopy", False)
    assert store.objects[item.replacement] == (b"replacement", False)
    item.space.refresh_from_db()
    assert item.space.storage_bytes_used == (100 if item.row.makerspace_id is None else 93)


def assert_owner_retained(item, before):
    assert RestoreRollbackObject.objects.values().get(pk=item.row.pk) == before.row
    item.space.refresh_from_db()
    assert item.space.storage_bytes_used == before.quota


def freeze_module(item, store, monkeypatch):
    """Leave a valid frozen binding through the actual failed purge workflow."""
    with monkeypatch.context() as patch:
        patch.setattr(store, "delete_objects", ModuleStore.delete_objects.__get__(store))
        patch.setattr(store, "failure", "storage")
        with pytest.raises(ValidationError):
            purge_module(item.space, "events", actor(f"freeze-{uuid4().hex}"))
    receipt = ModulePurgeReceipt.objects.get(source_makerspace_id=item.space.pk)
    assert receipt.graph_purged_at is None
    assert [binding["id"] for binding in receipt.rollback_bindings] == [item.row.pk]
    store.calls.clear()
    store.client_requests.clear()
    return receipt
