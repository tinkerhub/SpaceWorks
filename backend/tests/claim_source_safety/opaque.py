"""Canonical persisted opaque component state, using the existing manifest fixtures."""
from apps.backup.models import B1RestoreComponentState, B1RestoreOperationState
from tests.backup.e7_partition_test_helpers import digest
from tests.backup.x07_installation_test_helpers import context, manifest_for, operation_values
from uuid import uuid4


def opaque(space):
    component_id = str(uuid4())
    case = context(manifest_for((), components=[{
        "component_id": component_id, "makerspace_id": space.pk,
        "ciphertext_sha256": digest(f"claim-component-{space.pk}"),
    }]))
    operation = B1RestoreOperationState.objects.create(**operation_values(case))
    return B1RestoreComponentState.objects.create(operation_id=operation.pk,
        artifact_id=operation.artifact_id, capture_id=operation.capture_id,
        component_id=component_id, makerspace_id_snapshot=space.pk,
        ciphertext_sha256=digest(f"claim-component-{space.pk}"),
        state=B1RestoreComponentState.State.PENDING)
