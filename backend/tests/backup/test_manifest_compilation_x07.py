"""Trusted manifest compilation rejects drift before it can advance a restore."""

from copy import deepcopy
import uuid

import pytest
from django.db import DatabaseError, transaction

from apps.backup import compound_restore_state
from apps.backup.compound_restore_expectation import compile_expectation
from apps.backup.models import B1RestoreComponentState, B1RestoreOperationState
from apps.backup.recipient_selection import BackupBuildError
from tests.backup.x07_assertion_test_helpers import assert_refuses, commitment, snapshot
from tests.backup.x07_installation_test_helpers import (
    GROUPS, TABLE, context, fence, installation_tables, manifest_for, operation_values,
    prepared, raw_entry, raw_stage, rehydrate, seal_fence, sql,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("group", (*GROUPS.values(), "sequence_reservations"))
@pytest.mark.parametrize("value", (None, {}, "missing"))
def test_manifest_groups_are_explicit_lists_not_inferred_from_retained_rows(
    installation_tables, group, value,
):
    manifest = manifest_for([("broad_fence", fence([uuid.uuid4()]))])
    if value == "missing": del manifest[group]
    else: manifest[group] = value
    with pytest.raises(BackupBuildError):
        compile_expectation(manifest, using="default")


@pytest.mark.parametrize("defect", ("component-duplicate", "component-bool", "component-digest", "tuple-duplicate", "unknown-component", "duplicate-members", "shared-conflict", "sequence-duplicate"))
def test_manifest_component_tuple_and_shared_definition_identity_is_exact(
    installation_tables, defect,
):
    ids = [uuid.uuid4(), uuid.uuid4()]
    manifest = manifest_for([("broad_fence", fence(ids))])
    if defect == "component-duplicate": manifest["slice_components"].append(deepcopy(manifest["slice_components"][0]))
    elif defect == "component-bool": manifest["slice_components"][0]["makerspace_id"] = True
    elif defect == "component-digest": manifest["slice_components"][0]["ciphertext_sha256"] = "invalid"
    elif defect == "tuple-duplicate": manifest["broad_fence_scopes"] *= 2
    elif defect in ("unknown-component", "duplicate-members"):
        fact = manifest["broad_fence_scopes"][0]
        fact["component_ids"].append(str(uuid.uuid4()) if defect == "unknown-component" else fact["component_ids"][0])
        manifest["broad_fence_scopes"][0] = seal_fence(fact)
    elif defect == "shared-conflict":
        fact = deepcopy(manifest["broad_fence_scopes"][0])
        fact["operations"] = ["insert"]
        manifest["broad_fence_scopes"].append(seal_fence(fact))
    else: manifest["sequence_reservations"] *= 2
    with pytest.raises(BackupBuildError):
        compile_expectation(manifest, using="default")


@pytest.mark.parametrize("defect", ("definition", "canonicalizer", "key-component", "salt"))
def test_commitments_compile_only_against_real_unique_rule_and_canonicalizer(
    installation_tables, defect,
):
    fact, _reserved = commitment([uuid.uuid4()])
    manifest = manifest_for([("commitment", fact)])
    if defect == "definition": fact["definition_sha256"] = "0" * 64
    elif defect == "canonicalizer": fact["canonicalizer_identity"] = "0" * 64
    elif defect == "key-component": fact["key_component_identities"][0]["canonicalizer_identity"] = "unreviewed"
    else: manifest["reservation_salt"] = "c2hvcnQ="
    with pytest.raises(BackupBuildError):
        compile_expectation(manifest, using="default")


@pytest.mark.parametrize("addition", ("arbitrary", "enforcement", "reservation_salt"))
def test_source_commitment_cannot_smuggle_target_executable_fields(installation_tables, addition):
    fact, _reserved = commitment([uuid.uuid4()])
    fact[addition] = {"predicate_sql": "false"} if addition != "reservation_salt" else "untrusted"
    case = context(manifest_for([("commitment", fact)]))
    assert not B1RestoreOperationState.objects.filter(pk=case.inputs.run_id).exists()
    with pytest.raises(DatabaseError, match="source fact"), transaction.atomic():
        rehydrate(case)
    assert not B1RestoreOperationState.objects.filter(pk=case.inputs.run_id).exists()


@pytest.mark.parametrize("defect", ("missing", "extra", "ciphertext", "makerspace", "state"))
def test_resident_components_must_exactly_match_signed_pending_inventory(
    installation_tables, defect,
):
    case = context(manifest_for([("broad_fence", fence([uuid.uuid4()]))]))
    row = B1RestoreOperationState.objects.create(**operation_values(case))
    expected = case.expected["components"][0]
    values = {
        "operation_id": row.pk, "artifact_id": row.artifact_id,
        "capture_id": row.capture_id, "component_id": expected["component_id"],
        "makerspace_id_snapshot": expected["makerspace_id"],
        "ciphertext_sha256": expected["ciphertext_sha256"], "state": "pending",
    }
    if defect == "ciphertext": values["ciphertext_sha256"] = "0" * 64
    if defect == "makerspace": values["makerspace_id_snapshot"] += 1
    if defect != "missing":
        component = B1RestoreComponentState.objects.create(**values)
        if defect == "state":
            B1RestoreComponentState.objects.filter(pk=component.pk).update(state="merging")
    if defect == "extra":
        B1RestoreComponentState.objects.create(**{
            **values, "component_id": uuid.uuid4(), "makerspace_id_snapshot": 8002,
        })
    for stage in ("main_restored", "roles_recreated", "state_rehydrated"):
        raw_stage(case, stage)
    if defect == "missing":
        # The FK refuses an orphan entry before the complete-inventory proof.
        before = snapshot(case)
        with pytest.raises(DatabaseError, match="backup_b1_reservation_component_fk"), transaction.atomic():
            raw_entry(case, case.expected["entries"][0], verified=True)
        assert snapshot(case) == before
    else:
        raw_entry(case, case.expected["entries"][0], verified=True)
    assert_refuses(case, stage="enforcement_installed", match="inventory|component")


def test_installer_rechecks_real_relation_oid_between_compile_and_entry_write(
    installation_tables, monkeypatch,
):
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    original = compound_restore_state.install_reservation_entry

    def replace_relation_then_install(**kwargs):
        sql(f"ALTER TABLE {TABLE} RENAME TO backup_x07_replaced")
        sql(f"CREATE TABLE {TABLE} (LIKE backup_x07_replaced INCLUDING ALL)")
        return original(**kwargs)

    before = snapshot(case)
    with monkeypatch.context() as patch:
        patch.setattr(compound_restore_state, "install_reservation_entry", replace_relation_then_install)
        with pytest.raises(BackupBuildError, match="compiled installation changed"):
            compound_restore_state.install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)
    # The actual DDL race and failed entry are atomic, so the original OID returns.
    assert snapshot(case) == before
    assert compile_expectation(case.manifest, using="default") == (case.text, case.sha)


def test_same_relation_name_with_new_catalog_oid_cannot_satisfy_frozen_binding(
    installation_tables,
):
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    compound_restore_state.install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)
    sql(f"ALTER TABLE {TABLE} RENAME TO backup_x07_old_target")
    sql(f"CREATE TABLE {TABLE} (LIKE backup_x07_old_target INCLUDING ALL)")
    try:
        assert sql("SELECT %s::regclass::oid", [TABLE])[0][0] != case.expected["entries"][0]["target_relation_oid"]
        assert_refuses(case, match="expected target catalog identity changed")
    finally:
        sql(f"DROP TABLE {TABLE} CASCADE")
        sql(f"ALTER TABLE backup_x07_old_target RENAME TO {TABLE}")
