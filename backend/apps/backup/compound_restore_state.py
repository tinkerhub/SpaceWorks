"""Rehydrate and prove E7 state before a compound pointer can move."""

import json
import uuid

from django.db import transaction
from django.utils import timezone

from apps.backup.models import (
    B1FenceContinuity,
    B1ReservationEntry,
    B1RestoreComponentState,
    B1RestoreOperationState,
)
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_enforcement import install_reservation_entry
from apps.backup.compound_restore_expectation import (
    compile_expectation, component_map, digest, require_expectation,
)
from apps.backup.compound_restore_catalog import (
    _fence_declarations, _relation_declaration, prove_installation,
)


def rehydrate_pre_cutover_state(*, inputs, manifest, sibling, using="default"):
    """Persist opaque component identity before installing any reservation."""

    components = component_map(manifest)
    seeds = manifest.get("not_restored_seeds")
    if not isinstance(seeds, list) or {
        (item.get("component_id"), item.get("makerspace_id"), item.get("state"))
        for item in seeds if isinstance(item, dict)
    } != {
        (str(identity), fact["makerspace_id"], "pending")
        for identity, fact in components.items()
    }:
        raise BackupBuildError("The signed not-restored seed set is inconsistent.")
    expected_text, expected_sha256 = compile_expectation(manifest, using=using)
    operation_values = {
        "expected_installation": expected_text,
        "expected_installation_sha256": expected_sha256,
        "artifact_id": uuid.UUID(manifest["artifact_id"]),
        "capture_id": uuid.UUID(manifest["capture_id"]),
        "main_component_id": uuid.UUID(manifest["main_component"]["component_id"]),
        "outer_ciphertext_sha256": inputs.artifact_sha256,
        "outer_manifest_sha256": digest(manifest),
        "source_proof_sha256": digest(manifest["source_partition_proof"]),
        "sibling_database_name": sibling.identity.database_name,
        "sibling_database_oid": sibling.identity.database_oid,
        "sibling_server_identity": digest(list(sibling.identity.durable_key())),
    }
    with transaction.atomic(using=using):
        operation, created = B1RestoreOperationState.objects.using(using).get_or_create(
            operation_id=inputs.run_id, defaults=operation_values
        )
        operation = B1RestoreOperationState.objects.using(using).select_for_update().get(
            pk=operation.pk
        )
        if not created and any(
            getattr(operation, name) != value
            for name, value in operation_values.items()
            if name not in {"expected_installation", "expected_installation_sha256"}
        ):
            raise BackupBuildError("Existing compound restore state has another identity.")
        if operation.stage == B1RestoreOperationState.Stage.CUTOVER_READY:
            # Delayed merges may already have restored components and released guards.
            # Legacy terminal operations have no expectation to reproduce/backfill.
            if operation.expected_installation:
                require_expectation(operation, expected_text, expected_sha256)
            return {
                "operation_id": str(operation.operation_id),
                "not_restored_count": len(components), "persistent": True,
            }
        require_expectation(operation, expected_text, expected_sha256)
        _advance(operation, B1RestoreOperationState.Stage.MAIN_RESTORED, using)
        _advance(operation, B1RestoreOperationState.Stage.ROLES_RECREATED, using)
        for identity, fact in components.items():
            values = {
                "artifact_id": operation.artifact_id,
                "capture_id": operation.capture_id,
                "makerspace_id_snapshot": fact["makerspace_id"],
                "ciphertext_sha256": fact["ciphertext_sha256"],
                "state": B1RestoreComponentState.State.PENDING,
            }
            component, component_created = (
                B1RestoreComponentState.objects.using(using).get_or_create(
                    operation_id=operation.operation_id,
                    component_id=identity,
                    defaults=values,
                )
            )
            if not component_created and any(
                getattr(component, name) != value for name, value in values.items()
            ):
                raise BackupBuildError("Existing not-restored component facts changed.")
        _advance(operation, B1RestoreOperationState.Stage.STATE_REHYDRATED, using)
    return {
        "operation_id": str(operation.operation_id),
        "not_restored_count": len(components),
        "persistent": True,
    }


def install_manifest_enforcement(*, inputs, manifest, using="default"):
    """Consume the E7 installer for every signed component/fact binding."""

    expected_text, expected_sha256 = compile_expectation(manifest, using=using)
    expected = json.loads(expected_text)
    installed = 0
    for fact in expected["entries"]:
        # Each committed entry survives a crash before the next entry starts.
        with transaction.atomic(using=using):
            operation = B1RestoreOperationState.objects.using(using).select_for_update().get(
                pk=inputs.run_id
            )
            require_expectation(operation, expected_text, expected_sha256)
            if operation.stage not in (
                B1RestoreOperationState.Stage.STATE_REHYDRATED,
                B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED,
            ):
                if operation.stage in (
                    B1RestoreOperationState.Stage.CATALOG_VERIFIED,
                    B1RestoreOperationState.Stage.OBJECTS_VERIFIED,
                    B1RestoreOperationState.Stage.QUARANTINE_VERIFIED,
                    B1RestoreOperationState.Stage.CUTOVER_READY,
                ):
                    break
                raise BackupBuildError("Reservation installation is out of order.")
            lookup = {
                "operation_id": inputs.run_id,
                "component_id": fact["component_id"],
                "registry_identity": fact["registry_identity"], "kind": fact["kind"],
            }
            existing = B1ReservationEntry.objects.using(using).filter(**lookup).first()
            if existing is not None:
                if (existing.definition_sha256 != fact["definition_sha256"]
                        or existing.safe_payload != fact["installed_payload"]
                        or existing.installed_at is None):
                    raise BackupBuildError("An installed reservation definition changed.")
                continue
            install_reservation_entry(
                operation_id=inputs.run_id, component_id=fact["component_id"],
                kind=fact["kind"], fact=fact["source_fact"],
                reservation_salt=manifest.get("reservation_salt"),
                expected_entry=fact, using=using,
            )
            installed += 1
    with transaction.atomic(using=using):
        operation = B1RestoreOperationState.objects.using(using).select_for_update().get(
            pk=inputs.run_id
        )
        require_expectation(operation, expected_text, expected_sha256)
        if operation.stage in (
            B1RestoreOperationState.Stage.STATE_REHYDRATED,
            B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED,
        ):
            prove_installation(operation, using=using)
        _advance(operation, B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED, using)
    return {"installed": installed, "state": "database-enforced"}


def verify_pre_cutover_state(*, inputs, manifest, using="default"):
    expected_text, expected_sha256 = compile_expectation(manifest, using=using)
    with transaction.atomic(using=using):
        operation = B1RestoreOperationState.objects.using(using).select_for_update().get(
            pk=inputs.run_id
        )
        require_expectation(operation, expected_text, expected_sha256)
        prove_installation(
            operation, catalog_verified=True, require_timestamps=False, using=using
        )
        reservations = B1ReservationEntry.objects.using(using).filter(
            operation_id=inputs.run_id
        )
        reservations.filter(catalog_verified_at__isnull=True).update(
            catalog_verified_at=timezone.now()
        )
        prove_installation(operation, catalog_verified=True, using=using)
        _advance(operation, B1RestoreOperationState.Stage.CATALOG_VERIFIED, using)
        count = reservations.count()
    return {
        "verified": True, "reservations": count,
        "fences": B1FenceContinuity.objects.using(using).filter(
            operation_id=inputs.run_id
        ).count(),
    }


def readiness_declarations(*, using="default"):
    return {
        "reservations": [_relation_declaration(
            "backup_b1reservationentry", using
        )],
        "fences": _fence_declarations(using),
        "not_restored": [_relation_declaration(
            "backup_b1restorecomponentstate", using
        )],
    }


def mark_quarantine_verified(*, inputs, using="default"):
    operation = B1RestoreOperationState.objects.using(using).get(pk=inputs.run_id)
    for stage in (
        B1RestoreOperationState.Stage.OBJECTS_VERIFIED,
        B1RestoreOperationState.Stage.QUARANTINE_VERIFIED,
        B1RestoreOperationState.Stage.CUTOVER_READY,
    ):
        _advance(operation, stage, using)
    return {"verified": True}


def _advance(operation, target, using):
    operation.refresh_from_db(using=using)
    if operation.stage == target:
        return
    if operation.stage == B1RestoreOperationState.Stage.FAILED:
        raise BackupBuildError("A failed compound restore cannot resume forward.")
    ranks = [
        B1RestoreOperationState.Stage.VERIFIED,
        B1RestoreOperationState.Stage.MAIN_RESTORED,
        B1RestoreOperationState.Stage.ROLES_RECREATED,
        B1RestoreOperationState.Stage.STATE_REHYDRATED,
        B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED,
        B1RestoreOperationState.Stage.CATALOG_VERIFIED,
        B1RestoreOperationState.Stage.OBJECTS_VERIFIED,
        B1RestoreOperationState.Stage.QUARANTINE_VERIFIED,
        B1RestoreOperationState.Stage.CUTOVER_READY,
    ]
    if ranks.index(operation.stage) > ranks.index(target):
        return
    changed = B1RestoreOperationState.objects.using(using).filter(
        pk=operation.pk, stage=operation.stage
    ).update(stage=target)
    if changed != 1:
        raise BackupBuildError("Compound restore state did not advance exactly once.")
    operation.stage = target
