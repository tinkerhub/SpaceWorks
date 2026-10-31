"""Real commitment inputs and side-effect checks for target refusal tests."""

from copy import deepcopy
import uuid

import pytest
from django.db import DatabaseError, transaction

from apps.backup.compound_restore_target import DatabaseStateTarget
from apps.backup.models import B1ReservationEntry, B1RestoreOperationState
from apps.backup.postgres_client import server_major
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.reservation_keys import (
    CanonicalComponent, reservation_commitment, reservation_key_v1,
)
from apps.backup.reservation_registry import (
    canonicalizer_identity, component_canonicalizer_identities,
)
from tests.backup.x07_installation_test_helpers import TABLE, operation, raw_stage


def commitment(component_ids, *, table=TABLE, column="token", salt=b"s" * 32):
    rule = next(
        rule for rule in load_unique_rules()
        if rule.table == table and len(rule.components) == 1
        and rule.components[0].source_column == column
    )
    reserved = uuid.uuid4()
    key = reservation_key_v1(
        rule.identity, [CanonicalComponent(rule.components[0].type_identity, reserved.bytes)],
        nulls_not_distinct=rule.nulls_not_distinct,
    )
    major = server_major()
    return {
        "constraint_identity": rule.identity, "definition_sha256": rule.definition_sha256,
        "canonicalizer_identity": canonicalizer_identity(rule, major),
        "key_component_identities": list(component_canonicalizer_identities(rule, major)),
        "component_commitments": [
            {"component_id": str(value), "commitments": [reservation_commitment(salt, key)]}
            for value in sorted(component_ids, key=str)
        ],
    }, reserved


def snapshot(case):
    row = operation(case)
    return (
        row.stage, row.updated_at,
        list(B1ReservationEntry.objects.filter(operation_id=row.pk).order_by("pk").values_list(
            "pk", "installed_at", "catalog_verified_at",
        )),
    )


def assert_refuses(case, *, stage=B1RestoreOperationState.Stage.CATALOG_VERIFIED,
                   match="inventory|reservation|continuity|trigger|catalog|sequence|component|expected"):
    before = snapshot(case)
    with pytest.raises(DatabaseError, match=match), transaction.atomic():
        raw_stage(case, stage)
    assert snapshot(case) == before
    target = DatabaseStateTarget(using="default", acknowledgement=None)
    with pytest.raises(BackupBuildError):
        target.verify_catalog(case.sibling, case.inputs, case.manifest)
    assert snapshot(case) == before


def changed(value, path, replacement):
    result = deepcopy(value)
    parent = result
    for name in path[:-1]:
        parent = parent[name]
    parent[path[-1]] = replacement
    return result
