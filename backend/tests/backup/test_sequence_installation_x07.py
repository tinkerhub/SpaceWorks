"""Actual signed sequence catalog and persisted frontier, in both directions."""

import json
import uuid

import pytest

from apps.backup.compound_restore_state import install_manifest_enforcement
from apps.backup.compound_restore_target import DatabaseStateTarget
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.source_verifier import _verify_sequence_high_water
from tests.backup.x07_assertion_test_helpers import assert_refuses
from tests.backup.x07_installation_test_helpers import (
    OTHER_TABLE, context, fence, installation_tables, install_entries, manifest_for,
    operation, prepared, raw_stage, rehydrate, sql, trigger_oid,
)


pytestmark = pytest.mark.django_db(transaction=True)
SEQUENCE = "backup_x07_frontier_seq"
OWNER = "backup_x07_sequence_owner"


@pytest.fixture(params=(1, -1), ids=("ascending", "descending"))
def frontier(request, installation_tables):
    step = request.param
    start = 100 * step
    minimum, maximum = (1, 10000) if step > 0 else (-10000, -1)
    sql(f"CREATE TABLE {OWNER} (id bigint PRIMARY KEY)")
    sql(f"CREATE SEQUENCE {SEQUENCE} AS bigint INCREMENT {step} START {start} "
        f"MINVALUE {minimum} MAXVALUE {maximum} CACHE 1 NO CYCLE OWNED BY {OWNER}.id")
    sql(f"INSERT INTO {OWNER} VALUES (%s)", [start])
    sql("SELECT setval(%s::regclass, %s, true)", [SEQUENCE, start])
    try:
        yield step
    finally:
        sql(f"DROP SEQUENCE IF EXISTS {SEQUENCE} CASCADE")
        sql(f"DROP TABLE {OWNER} CASCADE")


def _sequence_case():
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    install_entries(case)
    fact = next(f for f in case.expected["sequences"] if f["sequence"] == SEQUENCE)
    assert fact["table"] == OWNER and fact["column"] == "id"
    assert fact["type_identity"] == "pg_catalog.int8:bigint"
    assert sql(f"SELECT last_value, is_called FROM {SEQUENCE}") == [(fact["installed_last_value"], True)]
    assert _prove(case)
    assert operation(case).stage == "state_rehydrated" and trigger_oid() > 0
    return case, fact


def _prove(case):
    return sql("SELECT public.backup_b1_prove_sequences(%s::jsonb)", [
        json.dumps(case.expected["sequences"]),
    ])[0][0]


SEQUENCE_DEFECTS = (
    "unowned", "wrong-owner", "column-type", "increment", "start", "minimum",
    "maximum", "cycle", "cache", "missing", "regresses", "uncalled",
    "next-collision", "out-of-range-next",
)


@pytest.mark.parametrize("defect", SEQUENCE_DEFECTS)
def test_actual_sequence_drift_refuses_python_and_raw_stage(frontier, defect):
    case, fact = _sequence_case()
    step = frontier
    if defect == "unowned": sql(f"ALTER SEQUENCE {SEQUENCE} OWNED BY NONE")
    elif defect == "wrong-owner": sql(f"ALTER SEQUENCE {SEQUENCE} OWNED BY {OTHER_TABLE}.id")
    elif defect == "column-type": sql(f"ALTER TABLE {OWNER} ALTER COLUMN id TYPE integer")
    elif defect == "increment": sql(f"ALTER SEQUENCE {SEQUENCE} INCREMENT BY {2 * step}")
    elif defect == "start": sql(f"ALTER SEQUENCE {SEQUENCE} START WITH {101 * step}")
    elif defect == "minimum": sql(f"ALTER SEQUENCE {SEQUENCE} MINVALUE {2 if step > 0 else -9999}")
    elif defect == "maximum": sql(f"ALTER SEQUENCE {SEQUENCE} MAXVALUE {9999 if step > 0 else -2}")
    elif defect == "cycle": sql(f"ALTER SEQUENCE {SEQUENCE} CYCLE")
    elif defect == "cache": sql(f"ALTER SEQUENCE {SEQUENCE} CACHE 2")
    elif defect == "missing": sql(f"DROP SEQUENCE {SEQUENCE}")
    elif defect == "regresses":
        sql("SELECT setval(%s::regclass, %s, true)", [SEQUENCE, fact["installed_last_value"] - step])
    elif defect == "uncalled":
        sql("SELECT setval(%s::regclass, %s, false)", [SEQUENCE, fact["installed_last_value"]])
    elif defect == "next-collision":
        sql(f"INSERT INTO {OWNER} VALUES (%s)", [fact["next_generated_value"]])
    elif defect == "out-of-range-next":
        sql("SELECT setval(%s::regclass, %s, true)", [
            SEQUENCE, fact["maximum"] if step > 0 else fact["minimum"],
        ])
    else: raise AssertionError(defect)
    assert _prove(case) is False
    assert_refuses(case, stage="enforcement_installed", match="sequence")


@pytest.mark.parametrize("defect", ("missing-declaration", "extra-declaration"))
def test_signed_sequence_set_must_exactly_equal_owned_public_catalog(frontier, defect):
    manifest = manifest_for([("broad_fence", fence([uuid.uuid4()]))])
    fact = next(f for f in manifest["sequence_reservations"] if f["sequence"] == SEQUENCE)
    if defect == "missing-declaration":
        manifest["sequence_reservations"].remove(fact)
    else:
        manifest["sequence_reservations"].append({**fact, "sequence": "absent_x07_sequence"})
    case = context(manifest)
    rehydrate(case)
    install_entries(case)
    assert _prove(case) is False
    assert_refuses(case, stage="enforcement_installed", match="sequence")


def test_control_row_consumption_and_retry_gaps_are_monotonic_not_drift(frontier):
    case, fact = _sequence_case()
    signed_sequences = json.dumps(case.expected["sequences"], sort_keys=True)
    # Actual B1 reservation/continuity inserts have already consumed their own
    # signed sequences. A failed transaction also leaves legitimate nextval gaps.
    from django.db import transaction
    with pytest.raises(RuntimeError, match="retry gap"), transaction.atomic():
        sql("SELECT nextval(pg_get_serial_sequence('backup_b1reservationentry', 'id'))")
        sql("SELECT nextval(pg_get_serial_sequence('backup_b1reservationentry', 'id'))")
        raise RuntimeError("retry gap")
    sql("SELECT nextval(%s::regclass)", [SEQUENCE])
    assert _prove(case)
    # Source readable-main reconstruction deliberately retains its exact check.
    with pytest.raises(BackupBuildError, match="high-water is incorrect"):
        _verify_sequence_high_water("default", (fact,))
    assert install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)["installed"] == 0
    assert install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)["installed"] == 0
    assert DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
        case.sibling, case.inputs, case.manifest,
    )["verified"]
    raw_stage(case, "objects_verified")
    assert json.dumps(case.expected["sequences"], sort_keys=True) == signed_sequences
