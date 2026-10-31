from io import BytesIO
from types import SimpleNamespace
import uuid

import pytest

from apps.backup import slice_merge
from apps.backup.models import (
    B1ReservationEntry,
    B1RestoreComponentState,
    B1RestoreOperationState,
)
from apps.backup.not_restored import is_not_restored
from tests.backup.x07_installation_test_helpers import (
    fence, finish_installation, operation, prepared,
)
from apps.backup.slice_merge_types import (
    BOUNDARY_FINAL,
    BOUNDARY_KEYS,
    BOUNDARY_OBJECTS,
    BOUNDARY_ROWS,
    BOUNDARY_STAGED,
    SliceMergeError,
    SliceMergeInput,
    SliceMergeInterrupted,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _state(*, dependency_space=None):
    ids = [uuid.uuid4()]
    if dependency_space:
        ids.append(uuid.uuid4())
    components = [
        {"component_id": str(value), "makerspace_id": space, "ciphertext_sha256": "d" * 64}
        for value, space in zip(ids, [880008, dependency_space])
    ]
    case = prepared([("broad_fence", fence(
        ids, table="inventory_inventoryproduct",
    ))], components=components)
    finish_installation(case)
    current_operation = operation(case)
    component = B1RestoreComponentState.objects.get(
        operation_id=current_operation.pk, makerspace_id_snapshot=880008,
    )
    reservation = B1ReservationEntry.objects.get(
        operation_id=current_operation.pk, component_id=component.component_id,
    )
    return current_operation, component, reservation


def _patch_pipeline(monkeypatch):
    group = SimpleNamespace(
        schema="unused", component_ids=(), fixtures=(), deltas=(), tables=frozenset()
    )
    monkeypatch.setattr(slice_merge, "recipient_fingerprint", lambda _identity: "1" * 64)
    monkeypatch.setattr(slice_merge, "validate_outer", lambda *_args: {})
    monkeypatch.setattr(slice_merge, "decrypt_file", lambda *_args: None)
    monkeypatch.setattr(slice_merge, "extract_slice", lambda *_args: None)
    monkeypatch.setattr(
        slice_merge, "validate_plaintext",
        lambda *_args: {"storage": {"objects": []}, "sealed_deks": []},
    )
    monkeypatch.setattr(slice_merge, "provision_merge_role", lambda **_kwargs: None)
    monkeypatch.setattr(slice_merge, "staging_schema_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(slice_merge, "stage_group", lambda *_args, **_kwargs: group)
    monkeypatch.setattr(slice_merge, "stage_objects", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(slice_merge, "install_target_deks", lambda *_args: ())
    monkeypatch.setattr(slice_merge, "add_target_deks", lambda current, *_args, **_kwargs: current)
    monkeypatch.setattr(slice_merge, "dependency_facts", lambda *_args: [])
    monkeypatch.setattr(slice_merge, "apply_staged", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(slice_merge, "promote_objects", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(slice_merge, "verify_promoted", lambda *_args: None)
    monkeypatch.setattr(slice_merge, "verify_staged_rows", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(slice_merge, "verify_target_deks", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        slice_merge, "_verify_constraints_and_reservations", lambda *_args, **_kwargs: None
    )


@pytest.mark.parametrize("boundary", [
    BOUNDARY_STAGED, BOUNDARY_KEYS, BOUNDARY_ROWS, BOUNDARY_OBJECTS, BOUNDARY_FINAL,
])
def test_crash_at_every_boundary_keeps_component_hidden_and_reservations(
    boundary, tmp_path, monkeypatch
):
    operation, component, reservation = _state()
    _patch_pipeline(monkeypatch)
    ciphertext = tmp_path / "slice.age"
    ciphertext.write_bytes(b"opaque")

    def crash(name):
        if name == boundary:
            raise SliceMergeInterrupted()

    with pytest.raises(SliceMergeInterrupted):
        slice_merge.merge_slices(
            operation.operation_id, {}, [SliceMergeInput(
                component.component_id, ciphertext, BytesIO(b"private identity")
            )],
            journal_path=tmp_path / "merge.journal", boundary_hook=crash,
        )

    component.refresh_from_db()
    assert component.state == B1RestoreComponentState.State.MERGING
    assert is_not_restored(component.makerspace_id_snapshot)
    assert B1ReservationEntry.objects.filter(pk=reservation.pk).exists()


def test_terminal_pre_apply_failure_retains_reservations(tmp_path, monkeypatch):
    operation, component, reservation = _state()
    _patch_pipeline(monkeypatch)
    ciphertext = tmp_path / "slice.age"
    ciphertext.write_bytes(b"opaque")

    with pytest.raises(SliceMergeError):
        slice_merge.merge_slices(
            operation.operation_id, {}, [SliceMergeInput(
                component.component_id, ciphertext, BytesIO(b"private identity")
            )],
            journal_path=tmp_path / "merge.journal",
            boundary_hook=lambda name: (_ for _ in ()).throw(RuntimeError("terminal"))
            if name == BOUNDARY_KEYS else None,
        )

    component.refresh_from_db()
    assert component.state == B1RestoreComponentState.State.FAILED
    assert is_not_restored(component.makerspace_id_snapshot)
    assert B1ReservationEntry.objects.filter(pk=reservation.pk).exists()


def test_only_successful_final_transaction_releases_reservations(tmp_path, monkeypatch):
    operation, component, reservation = _state()
    _patch_pipeline(monkeypatch)
    ciphertext = tmp_path / "slice.age"
    ciphertext.write_bytes(b"opaque")

    result = slice_merge.merge_slices(
        operation.operation_id, {}, [SliceMergeInput(
            component.component_id, ciphertext, BytesIO(b"private identity")
        )],
        journal_path=tmp_path / "merge.journal",
    )

    component.refresh_from_db()
    assert result["state"] == "restored"
    assert component.state == B1RestoreComponentState.State.RESTORED
    assert not is_not_restored(component.makerspace_id_snapshot)
    assert not B1ReservationEntry.objects.filter(pk=reservation.pk).exists()


def test_dependency_wait_retains_only_authenticated_component_facts(tmp_path, monkeypatch):
    operation, component, reservation = _state(dependency_space=880009)
    dependency = B1RestoreComponentState.objects.get(
        operation_id=operation.operation_id, makerspace_id_snapshot=880009,
    )
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(
        slice_merge, "dependency_facts",
        lambda *_args: [{
            "component_id": str(dependency.component_id),
            "reason": "declared_external_reference",
        }],
    )
    ciphertext = tmp_path / "slice.age"
    ciphertext.write_bytes(b"opaque")
    channel = BytesIO(b"identity-must-not-persist")

    result = slice_merge.merge_slices(
        operation.operation_id, {}, [SliceMergeInput(
            component.component_id, ciphertext, channel
        )],
        journal_path=tmp_path / "merge.journal",
    )

    component.refresh_from_db()
    assert result == {
        "state": "dependency_wait",
        "required_component_ids": [str(dependency.component_id)],
    }
    assert channel.closed
    assert component.state == B1RestoreComponentState.State.DEPENDENCY_WAIT
    assert component.merge_checkpoint == ""
    assert component.dependency_facts == [{
        "component_id": str(dependency.component_id),
        "reason": "declared_external_reference",
    }]
    assert B1ReservationEntry.objects.filter(pk=reservation.pk).exists()
    assert b"identity-must-not-persist" not in (tmp_path / "merge.journal").read_bytes()


def test_cross_linked_group_finishes_only_when_every_identity_is_supplied(
    tmp_path, monkeypatch
):
    operation, component, _reservation = _state(dependency_space=880010)
    dependency = B1RestoreComponentState.objects.get(
        operation_id=operation.operation_id, makerspace_id_snapshot=880010,
    )
    _patch_pipeline(monkeypatch)

    def facts(_root, current, _manifest):
        if current.component_id == component.component_id:
            return [{
                "component_id": str(dependency.component_id),
                "reason": "declared_external_reference",
            }]
        return []

    monkeypatch.setattr(slice_merge, "dependency_facts", facts)
    first = tmp_path / "first.age"
    second = tmp_path / "second.age"
    first.write_bytes(b"opaque-one")
    second.write_bytes(b"opaque-two")
    result = slice_merge.merge_slices(
        operation.operation_id, {}, [
            SliceMergeInput(component.component_id, first, BytesIO(b"identity-one")),
            SliceMergeInput(dependency.component_id, second, BytesIO(b"identity-two")),
        ],
        journal_path=tmp_path / "group.journal",
    )

    component.refresh_from_db()
    dependency.refresh_from_db()
    assert result["state"] == "restored"
    assert component.state == B1RestoreComponentState.State.RESTORED
    assert dependency.state == B1RestoreComponentState.State.RESTORED
