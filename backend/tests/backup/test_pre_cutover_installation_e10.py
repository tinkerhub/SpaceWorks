"""Lane E section 11 row 13: pre-cutover enforcement crash boundaries."""

import hashlib
import json
import uuid

import pytest

from django.db import connection

from apps.backup import compound_restore_state, reservation_enforcement
from apps.backup.models import B1FenceContinuity, B1ReservationEntry
from apps.backup.compound_restore_target import DatabaseStateTarget
from tests.backup.x07_installation_test_helpers import (
    TABLE, OTHER_TABLE, fence, installation_tables, operation, prepared, trigger_oid,
)
from tests.backup.x07_assertion_test_helpers import snapshot
from tests.backup.e7_reservation_test_helpers import persist_restore_state


pytestmark = pytest.mark.django_db(transaction=True)


class SimulatedInstallCrash(RuntimeError):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def _fence(component_id):
    fact = {
        "version": "b1-broad-unique-fence-v1",
        "constraint_identity": "1" * 64,
        "schema": "public",
        "table": TABLE,
        "columns": ["name"],
        "operations": ["insert", "update"],
        "component_ids": [str(component_id)],
    }
    fact["definition_sha256"] = _digest(fact)
    return fact


@pytest.mark.parametrize(
    "boundary",
    ("before_reservation_row", "after_reservation_row", "after_continuity_row"),
)
def test_single_fence_install_rolls_back_at_each_internal_boundary(
    boundary, monkeypatch, installation_tables
):
    """The existing one-entry primitive must never leave half a fence behind."""

    component_id = uuid.uuid4()
    fact = _fence(component_id)
    operation_id, state_component_id = persist_restore_state(fact)
    assert state_component_id == component_id
    if boundary == "before_reservation_row":
        monkeypatch.setattr(
            reservation_enforcement,
            "catalog_bound_payload",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                SimulatedInstallCrash(boundary)
            ),
        )
    elif boundary == "after_reservation_row":
        real_save = B1ReservationEntry.save

        def crash_after_reservation(row, *args, **kwargs):
            real_save(row, *args, **kwargs)
            raise SimulatedInstallCrash(boundary)

        monkeypatch.setattr(B1ReservationEntry, "save", crash_after_reservation)
    else:
        real_save = B1FenceContinuity.save

        def crash_after_continuity(row, *args, **kwargs):
            real_save(row, *args, **kwargs)
            raise SimulatedInstallCrash(boundary)

        monkeypatch.setattr(B1FenceContinuity, "save", crash_after_continuity)

    with pytest.raises(SimulatedInstallCrash, match=boundary):
        reservation_enforcement.install_reservation_entry(
            operation_id=operation_id,
            component_id=component_id,
            kind=B1ReservationEntry.Kind.BROAD_FENCE,
            fact=fact,
        )

    assert not B1ReservationEntry.objects.filter(operation_id=operation_id).exists()
    assert not B1FenceContinuity.objects.filter(operation_id=operation_id).exists()


def test_whole_install_commits_entries_then_resumes_without_duplicates(
    installation_tables, monkeypatch,
):
    ids = [uuid.uuid4()]
    case = prepared([
        ("broad_fence", fence(ids, table=TABLE, label="first")),
        ("broad_fence", fence(ids, table=OTHER_TABLE, label="second")),
    ])
    assert not connection.in_atomic_block
    original = compound_restore_state.install_reservation_entry
    calls = []

    def crash_on_next_entry(**kwargs):
        calls.append(kwargs["expected_entry"])
        if len(calls) == 2:
            first = calls[0]
            persisted = B1ReservationEntry.objects.get(operation_id=case.inputs.run_id)
            assert persisted.registry_identity == first["registry_identity"]
            assert persisted.installed_at and persisted.catalog_verified_at is None
            continuity = B1FenceContinuity.objects.get(operation_id=case.inputs.run_id)
            assert continuity.trigger_oids == [trigger_oid(first["installed_payload"]["table"])]
            raise SimulatedInstallCrash("next entry after a committed fence")
        return original(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(compound_restore_state, "install_reservation_entry", crash_on_next_entry)
        with pytest.raises(SimulatedInstallCrash, match="committed fence"):
            compound_restore_state.install_manifest_enforcement(
                inputs=case.inputs, manifest=case.manifest,
            )
    assert not connection.in_atomic_block
    assert operation(case).stage == "state_rehydrated"
    first_row = B1ReservationEntry.objects.get(operation_id=case.inputs.run_id)
    first_stamp = first_row.installed_at
    assert B1FenceContinuity.objects.filter(operation_id=case.inputs.run_id).count() == 1
    trigger_oid(calls[0]["installed_payload"]["table"])

    result = compound_restore_state.install_manifest_enforcement(
        inputs=case.inputs, manifest=case.manifest,
    )
    assert result["installed"] == 1
    assert operation(case).stage == "enforcement_installed"
    assert B1ReservationEntry.objects.filter(operation_id=case.inputs.run_id).count() == 2
    assert B1FenceContinuity.objects.filter(operation_id=case.inputs.run_id).count() == 2
    first_row.refresh_from_db()
    assert first_row.installed_at == first_stamp
    assert compound_restore_state.install_manifest_enforcement(
        inputs=case.inputs, manifest=case.manifest,
    )["installed"] == 0
    target = DatabaseStateTarget(using="default", acknowledgement=None)
    assert target.verify_catalog(case.sibling, case.inputs, case.manifest)["verified"]
    verified = snapshot(case)
    assert target.verify_catalog(case.sibling, case.inputs, case.manifest)["verified"]
    assert snapshot(case) == verified
    assert compound_restore_state.install_manifest_enforcement(
        inputs=case.inputs, manifest=case.manifest,
    )["installed"] == 0
    assert snapshot(case) == verified
