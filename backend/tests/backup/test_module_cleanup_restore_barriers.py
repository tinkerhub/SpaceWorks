"""Both module phases are invalidated before restore readiness, without rebinding."""
from unittest.mock import Mock

import pytest
from django.db import ProgrammingError, connection

from apps.backup import compound_restore_target, recovery
from apps.backup.compound_restore_target import DatabaseStateTarget
from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.restore_services import set_stage
from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.purge_receipt_recovery import invalidate_restored_receipts
from apps.tenant_migration import tenant_restore_target_state
from tests.backup.test_purge_receipt_restore_barriers import lineage
from tests.backup.test_restore_services import restore_fixture
from tests.makerspaces.module_cleanup_support import module_receipt, module_space
from tests.makerspaces.purge_test_support import receipt as global_receipt


def require_invalidated_before_normal(monkeypatch):
    original = DeploymentRecoveryState.save

    def save(state, *args, **kwargs):
        if state.mode == "normal":
            assert not ModulePurgeReceipt.objects.filter(invalidated_at__isnull=True).exists()
        return original(state, *args, **kwargs)

    monkeypatch.setattr(DeploymentRecoveryState, "save", save)


@pytest.mark.django_db
@pytest.mark.parametrize("completed", [False, True], ids=["pending-intent", "completed"])
@pytest.mark.parametrize("entry", ["legacy-complete", "quarantine-ack", "compound", "already-normal", "target"])
def test_restore_readiness_invalidates_module_authority_before_normal(entry, completed, monkeypatch):
    row = module_receipt(module_space(), completed=completed)
    original = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    generation = row.auth_generation
    global_row = global_receipt()
    require_invalidated_before_normal(monkeypatch)
    if entry in {"legacy-complete", "quarantine-ack"}:
        user, restore = restore_fixture(stage=RestoreOperation.Stage.VALIDATING)
        DeploymentRecoveryState.objects.filter(pk=1).update(mode="quiesced", active_restore=restore)
        if entry == "legacy-complete":
            set_stage(restore.pk, RestoreOperation.Stage.COMPLETED)
        else:
            recovery.enter_quarantine(restore, "raw restored locators")
            quarantined = DeploymentRecoveryState.objects.get(pk=1)
            assert quarantined.mode == "quarantined" and quarantined.auth_generation != generation
            row.refresh_from_db()
            global_row.refresh_from_db()
            assert row.invalidated_at and row.invalidation_reason == "recovery"
            assert row.auth_generation == generation and global_row.invalidated_at is not None
            DeploymentRecoveryState.objects.filter(pk=1).update(recovery_principal=user)
            recovery.acknowledge_quarantine(user, recovery.RESIDUAL_RISK)
    else:
        facts = lineage()
        monkeypatch.setattr(compound_restore_target, "query_live_database_identity", lambda _db: facts)
        monkeypatch.setattr(tenant_restore_target_state, "query_live_database_identity", lambda _db: facts)
        DeploymentRecoveryState.objects.filter(pk=1).update(mode="normal" if entry == "already-normal" else "target_import")
        if entry == "target":
            tenant_restore_target_state.set_target_normal(expected_identity=vars(facts))
        else:
            adapter = Mock()
            adapter.acknowledge.return_value = {"acknowledged": True}
            target = DatabaseStateTarget(using="default", acknowledgement=adapter)
            target.acknowledge_recovery(None, facts)
    after = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    assert after.pop("invalidated_at") is not None
    assert after.pop("invalidation_reason") == "recovery"
    original.pop("invalidated_at"); original.pop("invalidation_reason")
    assert after == original
    global_row.refresh_from_db()
    assert global_row.invalidated_at is not None
    state = DeploymentRecoveryState.objects.get(pk=1)
    assert state.mode == "normal"
    assert state.auth_generation == (quarantined.auth_generation if entry == "quarantine-ack" else generation)
    assert invalidate_restored_receipts() == 0


@pytest.mark.django_db
def test_missing_module_receipt_table_fails_readiness_closed_and_rolls_back_global_invalidation(monkeypatch):
    facts = lineage()
    row = global_receipt()
    DeploymentRecoveryState.objects.filter(pk=1).update(mode="target_import")
    monkeypatch.setattr(tenant_restore_target_state, "query_live_database_identity", lambda _db: facts)

    def unavailable(execute, sql, params, many, context):
        if "makerspaces_modulepurgereceipt" in sql:
            raise ProgrammingError("module receipt schema unavailable")
        return execute(sql, params, many, context)

    with connection.execute_wrapper(unavailable), pytest.raises(ProgrammingError, match="schema unavailable"):
        tenant_restore_target_state.set_target_normal(expected_identity=vars(facts))
    assert DeploymentRecoveryState.objects.get(pk=1).mode == "target_import"
    row.refresh_from_db()
    assert row.invalidated_at is None
