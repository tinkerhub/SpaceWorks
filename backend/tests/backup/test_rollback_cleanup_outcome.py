"""A free host lock or NORMAL alone never proves rollback cleanup is safe."""

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.backup import rollback_cleanup
from apps.backup.models import DeploymentRecoveryState, RestoreOperation, RestoreRollbackObject
from apps.backup.recovery import RESIDUAL_RISK
from apps.backup.rollback_cleanup_outcomes import RollbackCleanupOutcomeUnavailable
from tests.backup.rollback_cleanup_outcome_helpers import (
    assert_boundaries, assert_host_free, assert_refused, assert_retained, case,
    outcome_store, provider_boundary, recovery, run, snapshot,
)
from tests.backup.test_restore_services import restore_fixture
from tests.makerspaces.module_cleanup_support import module_store


pytestmark = pytest.mark.django_db(transaction=True)
Stage = RestoreOperation.Stage
Mode = DeploymentRecoveryState.Mode


@pytest.fixture(autouse=True)
def explicit_normal_cleanup_baseline():
    recovery(Mode.NORMAL, active=None)


@pytest.mark.parametrize("entry", ["direct", "expiry"])
@pytest.mark.parametrize("global_row", [False, True], ids=["known-maker", "global"])
def test_free_host_lock_does_not_authorize_paused_copy_cleanup(entry, global_row, outcome_store):
    item = case(outcome_store, stage=Stage.OBJECTS_RESTORING, global_row=global_row)
    recovery(Mode.QUIESCED, active=item.restore)
    before = snapshot(item, outcome_store)
    assert_host_free()
    assert_refused(entry, item.restore)
    assert_retained(item, outcome_store, before)


@pytest.mark.parametrize("stage,entry,global_row", [
    (Stage.FAILED, "direct", False),
    (Stage.FAILED, "expiry", True),
    (Stage.ABORTED, "direct", True),
])
def test_failed_or_aborted_normal_is_not_rollback_success(stage, entry, global_row, outcome_store):
    item = case(outcome_store, stage=stage, global_row=global_row)
    before = snapshot(item, outcome_store)
    assert_host_free()
    assert_refused(entry, item.restore)
    # Global rows have no quota owner; the unrelated Maker's counter stays intact.
    assert_retained(item, outcome_store, before)


def test_nonterminal_version_only_expiry_keeps_original_bytes_and_locator(outcome_store):
    item = case(outcome_store, stage=Stage.VALIDATING, version_only=True)
    # Even NORMAL cannot turn the old no-delete branch into a settled cleanup.
    before = snapshot(item, outcome_store)
    assert_host_free()
    assert_refused("expiry", item.restore)
    assert_retained(item, outcome_store, before)
    assert outcome_store.objects[item.original] == (b"oldcopy", False)
    assert before.row["source_version_id"] == item.original[2]


def test_completed_copy_cleanup_deletes_exact_versions_and_credits_once(outcome_store):
    item = case(outcome_store)
    untouched = {key: value for key, value in outcome_store.objects.items() if key not in item.copies}
    # A prefix sibling is never owned by this rollback row.
    sibling = outcome_store.put(item.original[0], item.row.copy_key + "-sibling", b"keep")
    untouched[sibling] = outcome_store.objects[sibling]
    observations = []

    def boundary(_params):
        assert_boundaries(item)
        assert RestoreRollbackObject.objects.filter(pk=item.row.pk).exists()
        item.space.refresh_from_db()
        assert item.space.storage_bytes_used == 100
        observations.append(True)

    outcome_store.on_list = boundary
    assert_host_free()
    assert run("direct", item.restore) == {"status": "cleaned", "cleaned": 1, "skipped": 0}
    assert observations and outcome_store.objects == untouched
    assert not RestoreRollbackObject.objects.filter(pk=item.row.pk).exists()
    item.space.refresh_from_db()
    assert item.space.storage_bytes_used == 93
    calls = list(outcome_store.calls)
    assert run("direct", item.restore) == {"status": "cleaned", "cleaned": 0, "skipped": 0}
    assert run("expiry", item.restore) == {"status": "checked", "cleaned": 0, "skipped": 0}
    item.space.refresh_from_db()
    assert item.space.storage_bytes_used == 93 and outcome_store.calls == calls


@pytest.mark.parametrize("fresh,cached", [(Stage.COMPLETED, Stage.FAILED), (Stage.FAILED, Stage.COMPLETED)])
def test_default_direct_uses_fresh_stage_instead_of_caller_stage(fresh, cached, outcome_store):
    item = case(outcome_store, stage=fresh, version_only=True)
    item.restore.stage = cached  # False caller data, never a terminal DB transition.
    before = snapshot(item, outcome_store)
    if fresh == Stage.FAILED:
        assert_refused("direct", item.restore)
        assert_retained(item, outcome_store, before)
    else:
        assert run("direct", item.restore) == {"status": "cleaned", "cleaned": 1, "skipped": 0}
        assert item.original not in outcome_store.objects
        assert outcome_store.objects == {item.replacement: (b"replacement", False)}
        assert not RestoreRollbackObject.objects.filter(pk=item.row.pk).exists()
        item.space.refresh_from_db()
        assert item.space.storage_bytes_used == 100


@pytest.mark.parametrize("fresh,cached", [(Stage.COMPLETED, Stage.FAILED), (Stage.FAILED, Stage.COMPLETED)])
def test_provider_boundary_reads_database_not_row_restore_cache(fresh, cached, outcome_store):
    item = case(outcome_store, stage=fresh, version_only=True)
    # A real ORM relation cache with deliberately false stage data. These fixtures
    # characterize defense at the boundary, not a legal COMPLETED -> FAILED move.
    item.row.restore.stage = cached
    assert item.row._state.fields_cache["restore"].stage == cached
    before = snapshot(item, outcome_store)
    with provider_boundary(item):
        if fresh == Stage.FAILED:
            with pytest.raises(RollbackCleanupOutcomeUnavailable):
                rollback_cleanup._delete_bytes(item.row)
        else:
            rollback_cleanup._delete_bytes(item.row)
    if fresh == Stage.FAILED:
        assert_retained(item, outcome_store, before)
    else:
        assert item.original not in outcome_store.objects
        assert outcome_store.objects == {item.replacement: (b"replacement", False)}
        assert outcome_store.calls == [("delete_version", {
            "Bucket": item.original[0], "Key": item.row.source_key, "VersionId": item.original[2],
        })]
        # This private byte boundary does not settle the locator or quota itself.
        assert RestoreRollbackObject.objects.values().get(pk=item.row.pk) == before.row
        item.space.refresh_from_db()
        assert item.space.storage_bytes_used == 100


def test_quarantine_requires_normal_but_allows_retained_acknowledgement_pointer(outcome_store):
    item = case(outcome_store, stage=Stage.RESTORED_QUARANTINED)
    now = timezone.now()
    recovery(Mode.QUARANTINED, active=item.restore, quarantined_at=now,
             recovery_principal=item.restore.requested_by)
    before = snapshot(item, outcome_store)
    assert_refused("expiry", item.restore)
    assert_refused("direct", item.restore)
    assert_retained(item, outcome_store, before)
    # Faithful persisted before/after acknowledge_quarantine baseline: NORMAL
    # retains active_restore provenance. This is not end-to-end recovery/rotation.
    state = recovery(Mode.NORMAL, active=item.restore, acknowledged_at=now,
                     acknowledged_by=item.restore.requested_by, acknowledgement=RESIDUAL_RISK)
    assert run("expiry", item.restore) == {"status": "checked", "cleaned": 1, "skipped": 0}
    state.refresh_from_db()
    assert state.mode == Mode.NORMAL and state.active_restore_id == item.restore.pk
    assert not RestoreRollbackObject.objects.filter(pk=item.row.pk).exists()
    assert all(key not in outcome_store.objects for key in item.copies)
    assert outcome_store.objects[item.original] == (b"oldcopy", False)
    item.space.refresh_from_db()
    assert item.space.storage_bytes_used == 93


@pytest.mark.parametrize("proof,entry,global_row", [
    ("missing-state", "direct", False),
    ("unknown-mode", "expiry", True),
    ("quiesced", "direct", True),
    ("quarantined", "expiry", False),
    ("active-nonterminal", "direct", False),
    ("active-unknown", "expiry", True),
    ("unknown-outcome", "expiry", False),
    ("missing-outcome", "direct", True),
])
def test_missing_or_inconsistent_outcome_proof_refuses_before_provider(proof, entry, global_row, outcome_store):
    item = case(outcome_store, global_row=global_row)
    selected = item.restore
    if proof == "missing-state":
        DeploymentRecoveryState.objects.filter(pk=1).delete()
    elif proof in {"unknown-mode", "quiesced", "quarantined"}:
        recovery({"unknown-mode": "unknown", "quiesced": Mode.QUIESCED, "quarantined": Mode.QUARANTINED}[proof])
    elif proof.startswith("active-"):
        stage = Stage.OBJECTS_RESTORING if proof == "active-nonterminal" else "unknown"
        _, active = restore_fixture(stage=stage)  # Different stage => unique user.
        recovery(Mode.NORMAL, active=active)
    elif proof == "unknown-outcome":
        # Deliberate invalid persisted fixture, not a supported service transition.
        RestoreOperation.objects.filter(pk=item.restore.pk).update(stage="unknown")
    else:
        selected = RestoreOperation(pk=uuid4(), stage=Stage.COMPLETED)
    before = snapshot(item, outcome_store)
    assert_host_free()
    assert_refused(entry, selected)
    assert_retained(item, outcome_store, before)


def test_mixed_expiry_retains_each_failed_row_once_and_cleans_healthy_owner(outcome_store):
    failed = case(outcome_store, stage=Stage.FAILED)
    global_row = RestoreRollbackObject.objects.create(
        restore=failed.restore, bucket_kind="private", source_key="global/original",
        copy_key=f"rollback/{failed.restore.pk}/private/global/original", size_bytes=7,
        expires_at=failed.row.expires_at,
    )
    global_identity = outcome_store.put(failed.original[0], global_row.copy_key, b"oldcopy")
    healthy = case(outcome_store, stage=Stage.COMPLETED)
    failed_before = snapshot(failed, outcome_store)
    global_before = RestoreRollbackObject.objects.values().get(pk=global_row.pk)
    healthy_originals = {key: value for key, value in outcome_store.objects.items() if key not in healthy.copies}
    assert run("expiry", healthy.restore) == {"status": "retained", "cleaned": 1, "skipped": 2}
    assert outcome_store.objects == healthy_originals
    assert outcome_store.objects[global_identity] == (b"oldcopy", False)
    assert RestoreRollbackObject.objects.values().get(pk=failed.row.pk) == failed_before.row
    assert RestoreRollbackObject.objects.values().get(pk=global_row.pk) == global_before
    assert not RestoreRollbackObject.objects.filter(pk=healthy.row.pk).exists()
    assert all(params.get("Prefix") == healthy.row.copy_key for method, params in outcome_store.calls if method == "list")
    failed.space.refresh_from_db()
    healthy.space.refresh_from_db()
    assert failed.space.storage_bytes_used == 100 and healthy.space.storage_bytes_used == 93
    # Repeat expiry reports only the two retained rows; no additional credit/I/O.
    calls = list(outcome_store.calls)
    assert run("expiry", healthy.restore) == {"status": "retained", "cleaned": 0, "skipped": 2}
    assert outcome_store.calls == calls and outcome_store.objects == healthy_originals
    healthy.space.refresh_from_db()
    assert healthy.space.storage_bytes_used == 93


def test_final_settlement_refuses_unsafe_fresh_outcome_before_counter_or_row_mutation(outcome_store):
    item = case(outcome_store, stage=Stage.FAILED)
    item.row.restore.stage = Stage.COMPLETED
    before = snapshot(item, outcome_store)
    # Isolated defense after locking: no illegal terminal transition is simulated,
    # and this test does not claim an end-to-end provider/DB race was exercised.
    with provider_boundary(item):
        with pytest.raises(RollbackCleanupOutcomeUnavailable):
            rollback_cleanup._settle(item.row)
    assert_retained(item, outcome_store, before)
