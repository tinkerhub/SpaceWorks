"""Full executable payload equality, valid kinds and shared fence installation."""

from copy import deepcopy
import uuid

import pytest
from django.db import DatabaseError, transaction

from apps.backup.compound_restore_state import install_manifest_enforcement
from apps.backup.compound_restore_target import DatabaseStateTarget
from apps.backup.models import B1FenceContinuity, B1ReservationEntry
from tests.backup.x07_assertion_test_helpers import assert_refuses, commitment, snapshot
from tests.backup.x07_installation_test_helpers import (
    TABLE, fence, installation_tables, operation, prepared, raw_entry,
    sql, trigger_oid,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ("commitment", "broad_fence", "relationship_fence", "object_namespace"))
def test_real_compiled_entry_kinds_install_and_verify(installation_tables, kind):
    ids = [uuid.uuid4()]
    fact = commitment(ids)[0] if kind == "commitment" else fence(ids, kind=kind)
    case = prepared([(kind, fact)])
    assert case.expected["entries"][0]["source_fact"] == fact
    assert install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)["installed"] == 1
    entry = B1ReservationEntry.objects.get(operation_id=case.inputs.run_id)
    assert entry.safe_payload == case.expected["entries"][0]["installed_payload"]
    assert entry.installed_at and entry.catalog_verified_at is None
    trigger_oid()
    result = DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
        case.sibling, case.inputs, case.manifest,
    )
    assert result == {"verified": True, "reservations": 1, "fences": int(kind != "commitment")}
    assert operation(case).stage == "catalog_verified"


@pytest.mark.parametrize("mode", ("ENABLE", "ENABLE ALWAYS"), ids=("O", "A"))
def test_legitimate_existing_origin_and_always_guards_are_accepted(installation_tables, mode):
    sql(f"CREATE TRIGGER backup_b1_reservation_guard BEFORE INSERT OR UPDATE OR DELETE "
        f"ON {TABLE} FOR EACH ROW EXECUTE FUNCTION public.backup_b1_enforce_reservations()")
    sql(f"ALTER TABLE {TABLE} {mode} TRIGGER backup_b1_reservation_guard")
    oid = trigger_oid()
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)
    DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
        case.sibling, case.inputs, case.manifest,
    )
    assert B1FenceContinuity.objects.get(operation_id=case.inputs.run_id).trigger_oids == [oid]


def test_shared_fence_across_components_has_one_exact_continuity_row(installation_tables):
    ids = [uuid.uuid4(), uuid.uuid4()]
    case = prepared([("broad_fence", fence(ids))])
    assert len(case.expected["entries"]) == 2
    assert install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)["installed"] == 2
    continuity = B1FenceContinuity.objects.get(operation_id=case.inputs.run_id)
    assert continuity.trigger_oids == [trigger_oid()]
    result = DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
        case.sibling, case.inputs, case.manifest,
    )
    assert result["reservations"] == 2 and result["fences"] == 1
    assert install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)["installed"] == 0


@pytest.mark.parametrize(
    "tamper", ("predicate", "salt", "canonicalizer-sql", "extra-json", "source-fact", "definition"),
)
def test_no_executable_or_arbitrary_payload_fields_can_be_stripped_before_proof(
    installation_tables, tamper,
):
    fact, _reserved = commitment([uuid.uuid4()])
    case = prepared([("commitment", fact)])
    expected = case.expected["entries"][0]
    payload = deepcopy(expected["installed_payload"])
    overrides = {}
    if tamper == "predicate": payload["enforcement"]["predicate_sql"] = "false"
    elif tamper == "salt": payload["reservation_salt"] = "dA=="
    elif tamper == "canonicalizer-sql": payload["enforcement"]["components"][0]["canonicalizer_sql"] = "NULL::bytea"
    elif tamper == "extra-json": payload["unreviewed_sql"] = {"predicate": "true"}
    elif tamper == "source-fact": payload["component_commitments"][0]["commitments"] = ["0" * 64]
    else: overrides["definition_sha256"] = "0" * 64
    entry = raw_entry(case, expected, verified=True, safe_payload=payload, **overrides)
    assert entry.installed_at and entry.catalog_verified_at and trigger_oid() > 0
    assert_refuses(case, stage="enforcement_installed", match="immutable compiled payload")


@pytest.mark.parametrize("tamper", ("extra", "missing", "wrong-component"))
def test_exact_reservation_inventory_is_required(installation_tables, tamper):
    ids = [uuid.uuid4(), uuid.uuid4()]
    case = prepared([("broad_fence", fence(ids))])
    expected = case.expected["entries"]
    raw_entry(case, expected[0], verified=True)
    if tamper != "missing": raw_entry(case, expected[1], verified=True)
    if tamper == "extra":
        raw_entry(case, expected[0], verified=True, registry_identity="0" * 64)
    if tamper == "wrong-component":
        # A nonresident component is rejected by the immediate composite FK.
        case = prepared([("broad_fence", fence([uuid.uuid4()]))], makerspace_id=9001)
        before = snapshot(case)
        with pytest.raises(DatabaseError, match="backup_b1_reservation_component_fk"), transaction.atomic():
            raw_entry(case, case.expected["entries"][0], verified=True, component_id=uuid.uuid4())
        assert snapshot(case) == before
        return
    trigger_oid()
    assert_refuses(case, stage="enforcement_installed")
