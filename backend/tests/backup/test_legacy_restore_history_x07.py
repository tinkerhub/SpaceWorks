"""Genuine pre-0025 history: unfinished refusal and valid delayed merges."""

import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.backup.compound_restore_state import install_manifest_enforcement
from apps.backup.compound_restore_target import DatabaseStateTarget
from apps.backup.models import B1ReservationEntry, B1RestoreComponentState
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.slice_merge_cleanup import clear_verified_reservations
from apps.backup.slice_merge_state import begin_merging, checkpoint, finalize, validate_component_states
from tests.backup.x07_assertion_test_helpers import snapshot
from tests.backup.x07_installation_test_helpers import (
    TABLE, context, fence, finish_installation, installation_tables, manifest_for,
    operation, operation_values, prepared, raw_stage, rehydrate, sql, trigger_oid,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def legacy_cases(installation_tables):
    """Let the real old schema create legacy blanks; never disable a guard."""
    cases = [
        context(manifest_for([("broad_fence", fence([uuid.uuid4()]))], makerspace_id=space))
        for space in (7101, 7102)
    ]
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    old_target = [("backup", "0024_archive_promotion_fencing")]
    try:
        executor.migrate(old_target)
        state = executor.loader.project_state(old_target).apps
        OldOperation = state.get_model("backup", "B1RestoreOperationState")
        OldComponent = state.get_model("backup", "B1RestoreComponentState")
        OldEntry = state.get_model("backup", "B1ReservationEntry")
        from django.utils import timezone
        for case, terminal in zip(cases, (False, True)):
            values = operation_values(case)
            values.pop("expected_installation")
            values.pop("expected_installation_sha256")
            row = OldOperation.objects.create(**values)
            component = case.expected["components"][0]
            OldComponent.objects.create(
                operation_id=row.pk, artifact_id=row.artifact_id, capture_id=row.capture_id,
                component_id=component["component_id"],
                makerspace_id_snapshot=component["makerspace_id"],
                ciphertext_sha256=component["ciphertext_sha256"], state="pending",
            )
            for stage in ("main_restored", "roles_recreated", "state_rehydrated"):
                raw_stage(case, stage)
            if terminal:
                entry = case.expected["entries"][0]
                OldEntry.objects.create(
                    operation_id=row.pk, component_id=entry["component_id"],
                    registry_identity=entry["registry_identity"], kind=entry["kind"],
                    definition_sha256=entry["definition_sha256"],
                    safe_payload=entry["installed_payload"], installed_at=timezone.now(),
                )
                for stage in ("enforcement_installed", "catalog_verified", "objects_verified",
                              "quarantine_verified", "cutover_ready"):
                    raw_stage(case, stage)
        MigrationExecutor(connection).migrate(leaves)
        yield cases
    finally:
        MigrationExecutor(connection).migrate(leaves)


def test_legacy_blank_unfinished_restore_requires_fresh_restore_actionably(legacy_cases):
    unfinished, _terminal = legacy_cases
    row = operation(unfinished)
    assert row.stage == "state_rehydrated"
    assert row.expected_installation == row.expected_installation_sha256 == ""
    before = snapshot(unfinished)
    with pytest.raises(DatabaseError, match="legacy unfinished.*fresh restore"), transaction.atomic():
        raw_stage(unfinished, "enforcement_installed")
    for action in (
        lambda: rehydrate(unfinished),
        lambda: install_manifest_enforcement(inputs=unfinished.inputs, manifest=unfinished.manifest),
        lambda: DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
            unfinished.sibling, unfinished.inputs, unfinished.manifest,
        ),
    ):
        with pytest.raises(BackupBuildError, match="Legacy unfinished.*fresh restore"):
            action()
        assert snapshot(unfinished) == before
    # Failing closed and reading/updating same-stage history remain possible.
    raw_stage(unfinished, "state_rehydrated")
    sql("UPDATE backup_b1restoreoperationstate SET stage='failed', failure_code='unattested' "
        "WHERE operation_id=%s", [unfinished.inputs.run_id])
    assert operation(unfinished).stage == "failed"


def test_legacy_cutover_ready_pending_components_remain_mergeable_history(legacy_cases):
    _unfinished, terminal = legacy_cases
    row = operation(terminal)
    components = list(B1RestoreComponentState.objects.filter(operation_id=row.pk))
    assert row.stage == "cutover_ready" and row.expected_installation == ""
    assert len(components) == 1 and components[0].state == "pending"
    assert B1ReservationEntry.objects.filter(operation_id=row.pk).count() == 1
    assert trigger_oid() > 0
    validate_component_states(row, components)
    assert rehydrate(terminal)["persistent"]
    assert operation(terminal).expected_installation == ""
    before = snapshot(terminal)
    raw_stage(terminal, "cutover_ready")
    assert snapshot(terminal) == before
    _verified_merge(row.pk, components)
    assert not B1ReservationEntry.objects.filter(operation_id=row.pk).exists()
    assert operation(terminal).stage == "cutover_ready"


def _verified_merge(operation_id, components):
    begin_merging(components, using="default")
    for value in ("staged", "keys_installed", "rows_applied", "objects_promoted", "verified"):
        checkpoint(components, value, using="default")
    finalize(operation_id, components, "unused_x07_merge_schema", using="default")


def test_verified_release_keeps_shared_guard_until_last_active_sibling(installation_tables):
    case = prepared([("broad_fence", fence([uuid.uuid4(), uuid.uuid4()]))])
    finish_installation(case)
    components = list(B1RestoreComponentState.objects.filter(
        operation_id=case.inputs.run_id,
    ).order_by("pk"))
    oid = trigger_oid()
    # Neither a caller nor the cleanup service may delete a pending reservation.
    with pytest.raises(DatabaseError, match="verified final merge"), transaction.atomic():
        clear_verified_reservations(case.inputs.run_id, [components[0].component_id])
    assert B1ReservationEntry.objects.filter(operation_id=case.inputs.run_id).count() == 2
    _verified_merge(case.inputs.run_id, components[:1])
    assert trigger_oid() == oid
    assert B1ReservationEntry.objects.filter(operation_id=case.inputs.run_id).count() == 1
    assert B1RestoreComponentState.objects.get(pk=components[1].pk).state == "pending"
    _verified_merge(case.inputs.run_id, components[1:])
    assert not B1ReservationEntry.objects.filter(operation_id=case.inputs.run_id).exists()
    assert sql("SELECT oid FROM pg_trigger WHERE tgrelid=%s::regclass "
               "AND tgname='backup_b1_reservation_guard'", [TABLE]) == []
    # Terminal history can be resumed after the original inventory is released.
    assert rehydrate(case)["persistent"]
    assert operation(case).stage == "cutover_ready"
