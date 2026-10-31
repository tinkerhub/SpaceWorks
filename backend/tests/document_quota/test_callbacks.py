"""Commit-only cleanup, original PK capture, conservative provider/accounting failures."""
import importlib

import pytest
from django.db import DatabaseError, connection, transaction

from apps.document_storage_quota import proven_document_charge, release_charge_once
from apps.makerspaces import limits
from apps.object_storage_lifecycle import storage_lifecycle
from tests.atomic_publication.store import error
from tests.document_safety.helpers import (
    assert_storage_boundary, cap, fail_after_audit, lab, snapshot, usage,
)
from tests.document_quota.helpers import RELEASE, delete, releases, upload
from tests.document_quota.version_store import VersionStore

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["receipt", "asset"])
def test_duplicate_post_delete_callbacks_and_receipts_cannot_double_credit(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    cap(case, 1000000, used=900)
    row, charge, _ = upload(case)
    proof = proven_document_charge(row, makerspace_id=case.home.pk)
    assert proof is not None
    original_pk = row.pk
    callbacks = []
    real_on_commit = transaction.on_commit
    def capture(callback, *args, **kwargs):
        callbacks.append(callback)
        return real_on_commit(callback, *args, **kwargs)
    monkeypatch.setattr(transaction, "on_commit", capture)
    signals = importlib.import_module(f"apps.{row._meta.app_label}.signals")
    handler = (signals.delete_to_buy_receipt_object if kind == "receipt"
               else signals.delete_warranty_document_object)
    case.store.boundary = lambda: assert_storage_boundary(case)
    with storage_lifecycle(case.home.pk) as guard:
        row._storage_guard = guard
        with transaction.atomic():
            # Duplicate delivery while PK still exists registers a second cleanup.
            handler(sender=case.model, instance=row, origin=row)
            row.delete()
        assert row.pk is None
        assert len(callbacks) == 2
        assert usage(case) == 900 and releases(case).count() == 1
        # Replay the captured proven obligation as well as the callback itself.
        assert release_charge_once(proof, verify=lambda: guard.verify(case.home.pk)) is False
        # Replaying the callback itself must also be inert after the row PK clears.
        for callback in callbacks:
            callback()
        assert usage(case) == 900 and releases(case).count() == 1
    release = releases(case).get()
    assert release.target_id == str(original_pk)
    assert release.meta["charge_event_uuid"] == str(charge.event_uuid)


@pytest.mark.parametrize("kind", ["receipt", "asset"])
def test_rollback_discards_cleanup_and_refund(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    row, _, _ = upload(case)
    pk = row.pk
    state, calls = snapshot(case), list(case.store.calls)
    with storage_lifecycle(case.home.pk) as guard:
        with pytest.raises(RuntimeError, match="rollback boundary"):
            with transaction.atomic():
                row._storage_guard = guard
                row.delete()
                assert not case.model.objects.filter(pk=pk).exists()
                raise RuntimeError("rollback boundary")
    assert snapshot(case) == state and case.store.calls == calls
    assert case.store.versions[row.object_key] and not releases(case).exists()


@pytest.mark.parametrize("kind", ["receipt", "asset"])
@pytest.mark.parametrize("failure", ["audit", "sql"])
def test_refund_and_release_marker_roll_back_together_after_physical_delete(
    kind, failure, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    cap(case, 1000000, used=900)
    row, _, body = upload(case)
    if failure == "audit":
        _, inserted = fail_after_audit(monkeypatch, RELEASE)
        exception = RuntimeError
    else:
        real_free = limits.free_storage
        def sql_failure(*args, **kwargs):
            real_free(*args, **kwargs)
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 / 0")
        monkeypatch.setattr(limits, "free_storage", sql_failure)
        exception = DatabaseError
    with pytest.raises(exception):
        delete(case, row)
    # The row delete committed before its callback; accounting is its own atomic
    # unit and must retain the full debit if its UPDATE/audit cannot both commit.
    assert not case.model.objects.filter(pk=row.pk).exists()
    assert not case.store.versions.get(row.object_key)
    assert usage(case) == 900 + len(body) and not releases(case).exists()
    if failure == "audit":
        assert len(inserted) == 1


@pytest.mark.parametrize("kind", ["receipt", "asset"])
def test_provider_failure_keeps_debit_after_row_delete(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    row, _, body = upload(case)
    def unavailable(_):
        raise error("AccessDenied", 403)
    case.store.before_delete = unavailable
    assert delete(case, row).status_code == 204
    assert not case.model.objects.filter(pk=row.pk).exists()
    assert case.store.versions[row.object_key]
    assert usage(case) == len(body) and not releases(case).exists()


@pytest.mark.parametrize("kind", ["receipt", "asset"])
@pytest.mark.parametrize("snapshot_kind", ["empty", "marker-only", "late-version"])
def test_only_nonempty_confirmed_data_snapshot_earns_credit(
    kind, snapshot_kind, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    store = VersionStore()
    case.store = store
    monkeypatch.setattr(case.module, "_client", lambda: store)
    monkeypatch.setattr(case.module, "_public_client", lambda: store)
    row, _, body = upload(case)
    key = row.object_key
    if snapshot_kind != "late-version":
        # Model an independent lifecycle/provider erasing all original versions.
        store.delete_objects(Bucket="fixture", Delete={"Objects": [
            {"Key": key, "VersionId": version} for version in list(store.versions[key])
        ]})
        if snapshot_kind == "marker-only":
            store.mark_deleted(key)
    else:
        store.before_delete = lambda _: store.seed(key, b"later imported version")
    assert delete(case, row).status_code == 204
    if snapshot_kind == "late-version":
        assert store.objects[key][0] == b"later imported version"
        assert usage(case) == 0 and releases(case).count() == 1
        # Only the original proven debit was released; no credit for late bytes.
        assert releases(case).get().meta["bytes"] == len(body)
    else:
        assert usage(case) == len(body) and not releases(case).exists()


@pytest.mark.parametrize("kind", ["receipt", "asset"])
@pytest.mark.parametrize("failure", [None, False, {"Errors": [{"Code": "AccessDenied"}]}])
def test_actual_partial_deletion_response_never_refunds(kind, failure, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    store = VersionStore(page_size=4000)
    case.store = store
    monkeypatch.setattr(case.module, "_client", lambda: store)
    monkeypatch.setattr(case.module, "_public_client", lambda: store)
    row, _, body = upload(case)
    # One real charged document, with subsequently retained provider versions.
    # Only its original debit is eligible, and no partial delete may settle it.
    for _ in range(1000):
        store.seed(row.object_key, b"retained version")
    store.delete_responses = [{}, failure]
    assert delete(case, row).status_code == 204
    assert not case.model.objects.filter(pk=row.pk).exists()
    assert len(store.versions[row.object_key]) == 1
    assert usage(case) == len(body) and not releases(case).exists()
