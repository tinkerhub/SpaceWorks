"""Restored locators cannot regain deletion authority, even with unchanged UUIDs."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.backup import compound_restore_target, recovery
from apps.backup.compound_restore_target import DatabaseStateTarget
from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.restore_services import set_stage
from apps.makerspaces.models import PurgeReceipt
from apps.makerspaces.purge_receipt_recovery import invalidate_restored_receipts
from apps.tenant_migration import tenant_restore_target_state
from tests.backup.test_restore_services import restore_fixture
from tests.makerspaces.purge_test_support import receipt

pytestmark = pytest.mark.django_db(transaction=True)


def lineage():
    return SimpleNamespace(database_uuid=str(uuid4()), run_id=str(uuid4()),
                           artifact_sha256="a" * 64, capture_id=str(uuid4()))


def assert_invalidated_before_normal(monkeypatch):
    save = DeploymentRecoveryState.save

    def checked(state, *args, **kwargs):
        if state.mode == DeploymentRecoveryState.Mode.NORMAL:
            assert not PurgeReceipt.objects.filter(invalidated_at__isnull=True).exists()
        return save(state, *args, **kwargs)

    monkeypatch.setattr(DeploymentRecoveryState, "save", checked)


def test_legacy_completed_restore_invalidates_surviving_receipts_without_generation_change(monkeypatch):
    row = receipt()
    _, restore = restore_fixture(stage=RestoreOperation.Stage.VALIDATING)
    DeploymentRecoveryState.objects.filter(pk=1).update(mode="quiesced", active_restore=restore)
    generation = DeploymentRecoveryState.objects.get(pk=1).auth_generation
    assert_invalidated_before_normal(monkeypatch)
    set_stage(restore.pk, RestoreOperation.Stage.COMPLETED)
    row.refresh_from_db()
    assert row.invalidated_at is not None
    assert DeploymentRecoveryState.objects.get(pk=1).auth_generation == generation


def test_raw_restore_quarantine_and_ack_invalidate_before_readmission(monkeypatch):
    row = receipt()
    user, restore = restore_fixture(stage=RestoreOperation.Stage.VALIDATING)
    recovery.enter_quarantine(restore, "raw disaster archive")
    row.refresh_from_db()
    first_invalidation = row.invalidated_at
    assert first_invalidation is not None
    state = DeploymentRecoveryState.objects.get(pk=1)
    state.recovery_principal = user
    state.save(update_fields=["recovery_principal"])
    # An old raw payload can carry a receipt whose generation already equals target.
    carried = receipt(source_id=2147000002)
    generation = state.auth_generation
    assert carried.auth_generation == generation
    assert_invalidated_before_normal(monkeypatch)
    recovery.acknowledge_quarantine(user, recovery.RESIDUAL_RISK)
    row.refresh_from_db(); carried.refresh_from_db(); state.refresh_from_db()
    assert row.invalidated_at == first_invalidation
    assert carried.invalidated_at is not None
    assert state.mode == "normal" and state.auth_generation == generation
    assert invalidate_restored_receipts() == 0


@pytest.mark.parametrize("initial_mode", ["target_import", "normal"], ids=["target-clear", "already-normal-resumed-ack"])
def test_compound_ack_invalidates_even_when_already_normal_and_generation_unchanged(
    initial_mode, monkeypatch,
):
    row = receipt()
    generation = row.auth_generation
    DeploymentRecoveryState.objects.filter(pk=1).update(mode=initial_mode)
    facts = lineage()
    # Host identity readback is supplied as the existing coordinator's verified fact;
    # readiness and all receipt/state changes use the actual target DB services.
    monkeypatch.setattr(compound_restore_target, "query_live_database_identity", lambda _db: facts)
    monkeypatch.setattr(tenant_restore_target_state, "query_live_database_identity", lambda _db: facts)
    adapter = Mock()
    adapter.acknowledge.return_value = {"acknowledged": True}
    assert_invalidated_before_normal(monkeypatch)
    target = DatabaseStateTarget(using="default", acknowledgement=adapter)
    assert target.acknowledge_recovery(None, facts)["recovery_mode"] == "normal"
    row.refresh_from_db()
    invalidated = row.invalidated_at
    assert invalidated is not None
    assert DeploymentRecoveryState.objects.get(pk=1).auth_generation == generation
    assert target.acknowledge_recovery(None, facts)["acknowledged"] is True
    row.refresh_from_db()
    assert row.invalidated_at == invalidated


def test_target_gate_cannot_clear_when_receipt_invalidation_fails(monkeypatch):
    receipt()
    facts = lineage()
    DeploymentRecoveryState.objects.filter(pk=1).update(mode="target_import")
    monkeypatch.setattr(tenant_restore_target_state, "query_live_database_identity", lambda _db: facts)
    monkeypatch.setattr("apps.makerspaces.purge_receipt_recovery.invalidate_restored_receipts", Mock(side_effect=RuntimeError("receipt table unavailable")))
    with pytest.raises(RuntimeError, match="receipt table unavailable"):
        tenant_restore_target_state.set_target_normal(expected_identity=vars(facts))
    assert DeploymentRecoveryState.objects.get(pk=1).mode == "target_import"
    assert PurgeReceipt.objects.filter(invalidated_at__isnull=True).exists()


def test_target_normal_invalidates_without_rebinding_receipt_authority(monkeypatch):
    row = receipt()
    before = PurgeReceipt.objects.values().get(pk=row.pk)
    facts = lineage()
    DeploymentRecoveryState.objects.filter(pk=1).update(mode="target_import")
    monkeypatch.setattr(tenant_restore_target_state, "query_live_database_identity", lambda _db: facts)
    tenant_restore_target_state.set_target_normal(expected_identity=vars(facts))
    after = PurgeReceipt.objects.values().get(pk=row.pk)
    assert after.pop("invalidated_at") is not None
    before.pop("invalidated_at")
    assert before == after
