import uuid

import pytest
from django.db import DatabaseError, transaction

from apps.accounts import rbac
from apps.accounts.models import User
from apps.backup.models import (
    B1FenceContinuity,
    B1ReservationEntry,
    B1RestoreComponentState,
    B1RestoreOperationState,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.backup.compound_restore_state import install_manifest_enforcement
from apps.backup.compound_restore_target import DatabaseStateTarget
from tests.backup.obsolete_contract_coordinator import assert_canonical_sibling_order
from tests.backup.obsolete_contract_host import (
    assert_legacy_compound_refusal, assert_restore_grant_edges,
)
from tests.backup.x07_installation_test_helpers import (
    context, fence, installation_tables, manifest_for, operation_values,
    prepared, raw_entry, raw_stage, trigger_oid,
)
from tests.backup.x07_assertion_test_helpers import assert_refuses, commitment


pytestmark = pytest.mark.django_db(transaction=True)

ORDERED_STAGES = (
    B1RestoreOperationState.Stage.VERIFIED,
    B1RestoreOperationState.Stage.MAIN_RESTORED,
    B1RestoreOperationState.Stage.ROLES_RECREATED,
    B1RestoreOperationState.Stage.STATE_REHYDRATED,
    B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED,
    B1RestoreOperationState.Stage.CATALOG_VERIFIED,
    B1RestoreOperationState.Stage.OBJECTS_VERIFIED,
    B1RestoreOperationState.Stage.QUARANTINE_VERIFIED,
    B1RestoreOperationState.Stage.CUTOVER_READY,
)


def _operation(*, stage=B1RestoreOperationState.Stage.VERIFIED):
    case = context(manifest_for([("broad_fence", fence(
        [uuid.uuid4()], table="inventory_inventoryproduct",
    ))]))
    operation = B1RestoreOperationState.objects.create(**operation_values(case))
    component = case.expected["components"][0]
    B1RestoreComponentState.objects.create(
        operation_id=operation.pk, artifact_id=operation.artifact_id,
        capture_id=operation.capture_id, component_id=component["component_id"],
        makerspace_id_snapshot=component["makerspace_id"],
        ciphertext_sha256=component["ciphertext_sha256"], state="pending",
    )
    for next_stage in ORDERED_STAGES[1:ORDERED_STAGES.index(stage) + 1]:
        if next_stage == B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED:
            install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)
        elif next_stage == B1RestoreOperationState.Stage.CATALOG_VERIFIED:
            DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
                case.sibling, case.inputs, case.manifest,
            )
        else:
            raw_stage(case, next_stage)
    operation.refresh_from_db()
    return operation


def test_restore_operation_declares_the_specified_nine_step_order():
    declared = tuple(
        value for value, _label in B1RestoreOperationState.Stage.choices
        if value != B1RestoreOperationState.Stage.FAILED
    )
    assert declared == ORDERED_STAGES


@pytest.mark.parametrize(
    ("start", "skipped"),
    tuple(zip(ORDERED_STAGES, ORDERED_STAGES[2:])),
)
def test_database_rejects_every_skipped_pre_cutover_step(start, skipped):
    operation = _operation(stage=start)

    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreOperationState.objects.filter(pk=operation.pk).update(stage=skipped)

    operation.refresh_from_db()
    assert operation.stage == start


def test_roles_and_grants_stage_cannot_be_skipped_before_any_later_django_stage():
    operation = _operation(stage=B1RestoreOperationState.Stage.MAIN_RESTORED)

    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreOperationState.objects.filter(pk=operation.pk).update(
            stage=B1RestoreOperationState.Stage.STATE_REHYDRATED
        )

    operation.refresh_from_db()
    assert operation.stage == B1RestoreOperationState.Stage.MAIN_RESTORED


def test_host_supervisor_reprovisions_grants_before_post_restore_django():
    assert_restore_grant_edges()


def test_b1_host_restore_uses_a_non_routable_sibling_until_cutover(monkeypatch, tmp_path):
    assert_legacy_compound_refusal()
    assert_canonical_sibling_order(monkeypatch, tmp_path)


def _crashed_boundary(boundary):
    space = Makerspace.objects.create(
        name=f"E7 crash {boundary}", slug=f"e7-crash-{boundary[:8]}-{uuid.uuid4().hex}"
    )
    actor = User.objects.create_user(
        username=f"e7-crash-{boundary}-{uuid.uuid4().hex}",
        role=User.Role.SPACE_MANAGER, access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=actor, makerspace=space, role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    ids = [uuid.uuid4()]
    fact, _reserved = commitment(ids)
    case = prepared([
        ("commitment", fact), ("broad_fence", fence(ids)),
        ("relationship_fence", fence(ids, kind="relationship_fence", label="relationship")),
    ], makerspace_id=space.pk)
    expected = {entry["kind"]: entry for entry in case.expected["entries"]}
    assert len(case.expected["entries"]) == 3
    assert len(case.expected["components"]) == 1
    assert not B1ReservationEntry.objects.filter(operation_id=case.inputs.run_id).exists()
    assert B1RestoreComponentState.objects.filter(
        operation_id=case.inputs.run_id, state="pending",
    ).count() == 1
    if boundary != "before-first-reservation":
        installed = boundary != "reservation-declared"
        raw_entry(case, expected["commitment"], installed=installed)
        if installed:
            trigger_oid()
    if boundary in {"fence-declared", "fence-installed"}:
        raw_entry(case, expected["broad_fence"], installed=boundary == "fence-installed")
    return case, actor, space


@pytest.mark.parametrize(
    "boundary",
    (
        "before-first-reservation", "reservation-declared",
        "reservation-installed", "fence-declared", "fence-installed",
    ),
)
def test_crash_at_every_installation_boundary_fails_closed_without_a_fence_gap(
    boundary, installation_tables,
):
    case, actor, space = _crashed_boundary(boundary)
    assert_refuses(
        case, stage=B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED,
        match="inventory|installed reservation",
    )
    assert rbac.can(actor, rbac.Action.VIEW_INVENTORY, space.pk) is False


def test_catalog_verification_requires_continuous_enabled_fence_evidence(
    installation_tables,
):
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    entry = raw_entry(case, case.expected["entries"][0], verified=True)
    assert entry.installed_at and entry.catalog_verified_at
    assert trigger_oid() > 0
    assert not B1FenceContinuity.objects.filter(operation_id=case.inputs.run_id).exists()
    raw_stage(case, B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED)

    assert_refuses(case, match="continuity inventory")


def test_continuity_evidence_cannot_be_deleted_or_disabled_after_installation():
    operation = _operation(stage=B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED)
    continuity = B1FenceContinuity.objects.get(operation_id=operation.pk)
    assert continuity.trigger_oids and continuity.enabled

    with pytest.raises(DatabaseError), transaction.atomic():
        B1FenceContinuity.objects.filter(pk=continuity.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        B1FenceContinuity.objects.filter(pk=continuity.pk).update(enabled=False)

    continuity.refresh_from_db()
    assert continuity.enabled is True
