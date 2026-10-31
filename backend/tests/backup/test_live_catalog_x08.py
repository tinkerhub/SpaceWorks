"""Real pg_trigger/OID and continuity proof on the canonical target adapter."""

import uuid

import pytest
from django.db import DatabaseError

from apps.backup.compound_restore_state import install_manifest_enforcement
from apps.backup.compound_restore_target import DatabaseStateTarget
from apps.backup.models import B1FenceContinuity, B1ReservationEntry, B1RestoreOperationState
from apps.backup.recipient_selection import BackupBuildError
from tests.backup.x07_assertion_test_helpers import assert_refuses, snapshot
from tests.backup.x07_installation_test_helpers import (
    TABLE, OTHER_TABLE, fence, installation_tables, operation_values, prepared,
    raw_entry, raw_stage, sql, trigger_oid,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _installed_without_continuity():
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    row = raw_entry(case, case.expected["entries"][0], verified=True)
    assert row.installed_at and row.catalog_verified_at
    oid = trigger_oid()
    assert not B1FenceContinuity.objects.filter(operation_id=case.inputs.run_id).exists()
    raw_stage(case, "enforcement_installed")
    return case, oid


@pytest.mark.parametrize(
    "defect", ("missing", "definition", "stale-oid", "string-oid", "another-operation-only", "extra"),
)
def test_continuity_is_exact_for_this_operation_and_current_guard(installation_tables, defect):
    case, oid = _installed_without_continuity()
    entry = case.expected["entries"][0]
    if defect != "missing":
        operation_id = case.inputs.run_id
        if defect == "another-operation-only":
            values = operation_values(case)
            values["operation_id"] = uuid.uuid4()
            other = B1RestoreOperationState.objects.create(**values)
            operation_id = other.pk
        oids = [oid + 1] if defect == "stale-oid" else [oid]
        if defect == "string-oid": oids = [str(oid)]
        B1FenceContinuity.objects.create(
            operation_id=operation_id, registry_identity=entry["registry_identity"],
            definition_sha256="0" * 64 if defect == "definition" else entry["definition_sha256"],
            trigger_oids=oids,
        )
    if defect == "extra":
        B1FenceContinuity.objects.create(
            operation_id=case.inputs.run_id, registry_identity="0" * 64,
            definition_sha256=entry["definition_sha256"], trigger_oids=[oid],
        )
    assert trigger_oid() == oid
    assert_refuses(case, match="continuity")


CATALOG_DEFECTS = (
    "missing", "disabled", "replica", "wrong-table", "stale-oid",
    "wrong-function", "events", "when", "columns", "arguments",
)


def _alter_guard(defect):
    if defect in ("disabled", "replica"):
        mode = "DISABLE" if defect == "disabled" else "ENABLE REPLICA"
        sql(f"ALTER TABLE {TABLE} {mode} TRIGGER backup_b1_reservation_guard")
        return
    sql(f"DROP TRIGGER backup_b1_reservation_guard ON {TABLE}")
    if defect == "missing": return
    table = OTHER_TABLE if defect == "wrong-table" else TABLE
    events = {
        "events": "BEFORE INSERT OR UPDATE",
        "columns": "BEFORE INSERT OR UPDATE OF note OR DELETE",
    }.get(defect, "BEFORE INSERT OR UPDATE OR DELETE")
    condition = "WHEN (true)" if defect == "when" else ""
    function = "public.backup_b1_enforce_reservations"
    if defect == "wrong-function":
        sql("CREATE FUNCTION public.backup_x07_wrong_guard() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$")
        function = "public.backup_x07_wrong_guard"
    arguments = "'unreviewed'" if defect == "arguments" else ""
    sql(f"CREATE TRIGGER backup_b1_reservation_guard {events} ON {table} "
        f"FOR EACH ROW {condition} EXECUTE FUNCTION {function}({arguments})")


@pytest.mark.parametrize("defect", CATALOG_DEFECTS)
def test_live_catalog_drift_refuses_sql_and_actual_target_without_stamping(
    installation_tables, defect,
):
    case, oid = _installed_without_continuity()
    entry = case.expected["entries"][0]
    B1FenceContinuity.objects.create(
        operation_id=case.inputs.run_id, registry_identity=entry["registry_identity"],
        definition_sha256=entry["definition_sha256"], trigger_oids=[oid],
    )
    _alter_guard(defect)
    if defect == "stale-oid": assert trigger_oid() != oid
    assert_refuses(case, match="trigger|continuity")


@pytest.mark.parametrize("defect", ("disabled", "replica", "wrong-function", "events", "when", "columns", "arguments"))
def test_installer_refuses_existing_same_name_unsafe_guard(installation_tables, defect):
    # Create a canonical guard without a reservation, then corrupt its structure.
    sql(f"CREATE TRIGGER backup_b1_reservation_guard BEFORE INSERT OR UPDATE OR DELETE "
        f"ON {TABLE} FOR EACH ROW EXECUTE FUNCTION public.backup_b1_enforce_reservations()")
    _alter_guard(defect)
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    before = snapshot(case)
    with pytest.raises((DatabaseError, BackupBuildError), match="unsafe|absent"):
        install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)
    assert snapshot(case) == before
    assert not B1ReservationEntry.objects.filter(operation_id=case.inputs.run_id).exists()
    assert not B1FenceContinuity.objects.filter(operation_id=case.inputs.run_id).exists()


@pytest.mark.parametrize("next_stage", ("objects_verified", "quarantine_verified", "cutover_ready"))
def test_each_later_forward_stage_rechecks_intervening_ddl(installation_tables, next_stage):
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)
    DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
        case.sibling, case.inputs, case.manifest,
    )
    for stage in ("objects_verified", "quarantine_verified"):
        if stage == next_stage: break
        raw_stage(case, stage)
    assert trigger_oid() > 0
    _alter_guard("disabled")
    assert_refuses(case, stage=next_stage, match="trigger")


def test_selected_manifest_mismatch_refuses_before_any_verification_timestamp(installation_tables):
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)
    before = snapshot(case)
    case.manifest = {**case.manifest, "user_closure_digest": "0" * 64}
    with pytest.raises(BackupBuildError, match="manifest|expectation changed"):
        DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
            case.sibling, case.inputs, case.manifest,
        )
    assert snapshot(case) == before


def test_missing_continuity_refuses_python_before_stamping_any_entry(installation_tables):
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    entry = raw_entry(case, case.expected["entries"][0])
    assert entry.installed_at and entry.catalog_verified_at is None
    assert trigger_oid() > 0
    raw_stage(case, "enforcement_installed")
    before = snapshot(case)
    with pytest.raises(BackupBuildError, match="complete pre-cutover installation proof failed"):
        DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
            case.sibling, case.inputs, case.manifest,
        )
    assert snapshot(case) == before
    assert not B1FenceContinuity.objects.filter(operation_id=case.inputs.run_id).exists()
