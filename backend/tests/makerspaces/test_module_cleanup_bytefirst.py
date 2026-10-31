"""Durable intent, byte-first retry, and single atomic quota/graph checkpoint."""
import pytest
from django.core.exceptions import ValidationError
from django.db import connections

from apps.audit.models import AuditLog
from apps.events.models import Event
from apps.makerspaces import module_purge_receipts
from apps.makerspaces.models import Makerspace, ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_storage import bucket_name
from tests.makerspaces.module_cleanup_support import module_store, purged_event_case, seed_versions


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("failure", ["storage", "partial", "acknowledgement", "readback"])
def test_provider_failure_keeps_committed_intent_locators_graph_and_frozen_charge(failure, module_store):
    space, user, event, key = purged_event_case(module_store)
    seed_versions(module_store, "public_image", key)
    # Latest current final is the accepted charge proof; old versions/markers don't multiply it.
    module_store.put(bucket_name("public_image"), key, b"x" * 4096)
    module_store.failure = failure
    observed = []

    def committed_before_delete(_bucket, _batch):
        db = connections["default"].copy()
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT exact_keys, charge_obligations FROM makerspaces_modulepurgereceipt")
                values = cursor.fetchone()
            assert values is not None, "intent was not visible outside the caller connection"
            observed.append(values)
        finally:
            db.close()
        assert Event.objects.filter(pk=event.pk).exists()
        assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 10000

    module_store.on_delete = committed_before_delete
    with pytest.raises(ValidationError):
        purge_module(space, "events", user)
    receipt = ModulePurgeReceipt.objects.get()
    assert observed and receipt.graph_purged_at is None and receipt.last_verified_at is None
    assert receipt.last_error_code == "cleanup_unconfirmed"
    assert receipt.exact_keys == [["public_image", key], ["public_image", f"staging/{key}"]]
    assert sum(row[3] for row in receipt.charge_obligations) == 4096
    assert Event.objects.filter(pk=event.pk).exists()
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 10000
    assert not AuditLog.objects.filter(action="makerspace.module_purged").exists()
    module_store.failure = None
    module_store.on_delete = None
    completed = retry_cleanup(receipt.pk, user)
    assert completed.pk == receipt.pk and completed.graph_purged_at
    assert not Event.objects.filter(pk=event.pk).exists()
    assert not module_store.has_key(bucket_name("public_image"), key)
    assert not module_store.has_key(bucket_name("public_image"), f"staging/{key}")
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 5904
    retry_cleanup(receipt.pk, user)
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 5904
    assert AuditLog.objects.filter(action="makerspace.module_purged").count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("failure", ["head", "listing", "unsupported"])
def test_preintent_provider_failure_has_no_irreversible_intent(failure, module_store):
    space, user, event, key = purged_event_case(module_store)
    module_store.failure = failure
    with pytest.raises(ValidationError):
        purge_module(space, "events", user)
    assert not ModulePurgeReceipt.objects.exists() and not module_store.deletes
    assert Event.objects.filter(pk=event.pk).exists()
    assert module_store.has_key(bucket_name("public_image"), key)
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 10000


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("phase", ["settlement", "audit", "checkpoint"])
def test_final_failure_rolls_back_graph_quota_audit_checkpoint_and_retries_same_charge(phase, module_store, monkeypatch):
    space, user, event, key = purged_event_case(module_store)
    with monkeypatch.context() as patch:
        if phase == "settlement":
            original = module_purge_receipts.settle

            def fail_settlement(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError("after debit")

            patch.setattr(module_purge_receipts, "settle", fail_settlement)
        elif phase == "audit":
            original = module_purge_receipts.audit.record

            def fail_audit(actor, action, **kwargs):
                result = original(actor, action, **kwargs)
                if action == "makerspace.module_purged":
                    raise RuntimeError("after final audit")
                return result

            patch.setattr(module_purge_receipts.audit, "record", fail_audit)
        else:
            original = ModulePurgeReceipt.save

            def fail_checkpoint(self, *args, **kwargs):
                result = original(self, *args, **kwargs)
                if self.graph_purged_at is not None:
                    raise RuntimeError("after checkpoint")
                return result

            patch.setattr(ModulePurgeReceipt, "save", fail_checkpoint)
        with pytest.raises(RuntimeError):
            purge_module(space, "events", user)
    receipt = ModulePurgeReceipt.objects.get()
    assert receipt.graph_purged_at is None and receipt.last_verified_at is None
    assert Event.objects.filter(pk=event.pk).exists()
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 10000
    assert not module_store.has_key(bucket_name("public_image"), key)
    assert sum(row[3] for row in receipt.charge_obligations) == 4096
    assert not AuditLog.objects.filter(action="makerspace.module_purged").exists()
    retry_cleanup(receipt.pk, user)
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 5904
    assert not Event.objects.filter(pk=event.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_process_loss_after_bytes_keeps_durable_intent_and_original_size(module_store, monkeypatch):
    space, user, event, key = purged_event_case(module_store)
    original = module_purge_receipts.purge_storage.delete_and_verify

    def process_loss(*args):
        original(*args)
        raise SystemExit("process died after storage readback")

    with monkeypatch.context() as patch:
        patch.setattr(module_purge_receipts.purge_storage, "delete_and_verify", process_loss)
        with pytest.raises(SystemExit):
            purge_module(space, "events", user)
    receipt = ModulePurgeReceipt.objects.get()
    assert receipt.graph_purged_at is None
    assert Event.objects.filter(pk=event.pk).exists()
    assert sum(row[3] for row in receipt.charge_obligations) == 4096
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 10000
    assert not module_store.has_key(bucket_name("public_image"), key)
    retry_cleanup(receipt.pk, user)
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 5904


@pytest.mark.django_db(transaction=True)
def test_changed_frozen_graph_refuses_rebase_before_provider(module_store):
    space, user, event, key = purged_event_case(module_store)
    module_store.failure = "storage"
    with pytest.raises(ValidationError):
        purge_module(space, "events", user)
    receipt = ModulePurgeReceipt.objects.get()
    Event.objects.create(makerspace=space, title="New graph", starts_at=event.starts_at, ends_at=event.ends_at)
    module_store.failure = None
    module_store.calls.clear()
    with pytest.raises(ValidationError, match="graph changed"):
        retry_cleanup(receipt.pk, user)
    assert module_store.calls == []
    assert Event.objects.filter(makerspace=space).count() == 2
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 10000


@pytest.mark.django_db(transaction=True)
def test_only_explicit_cleanup_actions_emit_global_audit_without_private_locators(module_store):
    space, user, _event, key = purged_event_case(module_store)
    receipt, _ = purge_module(space, "events", user)
    rows = list(AuditLog.objects.filter(action__startswith="makerspace.module_purg").order_by("id"))
    assert [row.action for row in rows] == ["makerspace.module_purge_started", "makerspace.module_purged"]
    assert all(row.makerspace_id is None and row.actor_id == user.pk for row in rows)
    assert rows[0].meta == {"receipt_id": str(receipt.pk), "makerspace_id": space.pk, "module": "events"}
    assert set(rows[1].meta) == {"receipt_id", "makerspace_id", "module", "counts", "verified"}
    assert rows[1].meta["verified"] is True
    assert key not in str([row.meta for row in rows])
    assert "staging/" not in str([row.meta for row in rows])
    retry_cleanup(receipt.pk, user)
    assert AuditLog.objects.filter(action="makerspace.module_purge_receipt_checked").count() == 1
    assert AuditLog.objects.filter(action="makerspace.module_purged").count() == 1
