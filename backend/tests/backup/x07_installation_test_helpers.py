"""Admitted manifest inputs, compiled before any retained restore rows exist.

Signature/source-proof admission has its own tests. These fixtures exercise the
real target services with every manifest group explicit, including all sequences.
"""

import base64
import hashlib
import json
from types import SimpleNamespace
import uuid

import pytest
from django.db import connection
from django.utils import timezone

from apps.backup.compound_restore_expectation import compile_expectation, digest
from apps.backup.compound_restore_state import rehydrate_pre_cutover_state
from apps.backup.main_projection import _install_sequence_high_water
from apps.backup.models import B1ReservationEntry, B1RestoreOperationState
from apps.backup.reservation_enforcement import install_reservation_entry
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.source_fences import broad_unique_fence
from apps.backup.source_sequence_reservations import sequence_facts


TABLE = "backup_x07_probe"
OTHER_TABLE = "backup_x07_other_probe"
GROUPS = {
    "commitment": "reservation_commitments", "broad_fence": "broad_fence_scopes",
    "relationship_fence": "relationship_fence_scopes",
    "object_namespace": "object_namespace_fences",
}


def sql(statement, parameters=None):
    with connection.cursor() as cursor:
        cursor.execute(statement, parameters)
        if cursor.description:
            return cursor.fetchall()


@pytest.fixture
def installation_tables():
    for table in (TABLE, OTHER_TABLE):
        sql(f'CREATE TABLE public.{table} '
            '(id bigint PRIMARY KEY, token uuid UNIQUE, note text, "étiquette" text UNIQUE)')
    try:
        yield
    finally:
        for table in (TABLE, OTHER_TABLE):
            sql(f"DROP TABLE IF EXISTS public.{table} CASCADE")
        sql("DROP FUNCTION IF EXISTS public.backup_x07_wrong_guard() CASCADE")


def fence(component_ids, *, kind="broad_fence", table=TABLE, label="broad"):
    ids = sorted(str(value) for value in component_ids)
    if kind == "broad_fence":
        column = "étiquette" if table in (TABLE, OTHER_TABLE) else "id"
        rule = next(
            rule for rule in load_unique_rules()
            if rule.table == table and len(rule.components) == 1
            and rule.components[0].source_column == column
        )
        return broad_unique_fence(rule, [
            {"component_id": value, "count": 1} for value in ids
        ])
    fact = {
        "version": {
            "broad_fence": "b1-broad-unique-fence-v1",
            "relationship_fence": "b1-relationship-fence-v1",
            "object_namespace": "b1-object-namespace-fence-v1",
        }[kind],
        "schema": "public", "table": table,
        "columns": ["note"],
        "operations": ["insert", "update"], "component_ids": ids,
        ("constraint_identity" if kind == "broad_fence" else "registry_identity"):
            hashlib.sha256(label.encode()).hexdigest(),
    }
    if kind == "relationship_fence":
        fact["dependency_kind"] = "boundary_inbound_fk"
        fact["columns"] = ["id"]
    if kind == "object_namespace":
        fact["bucket_kind"] = "public_image"
        fact["columns"] = ["note"]
    return seal_fence(fact)


def seal_fence(fact):
    fact = {key: value for key, value in fact.items() if key != "definition_sha256"}
    # Source fence hashing uses the producer's ASCII JSON contract.
    encoded = json.dumps(fact, sort_keys=True, separators=(",", ":")).encode()
    return {**fact, "definition_sha256": hashlib.sha256(encoded).hexdigest()}


def manifest_for(facts, *, components=None, makerspace_id=7001, salt=b"s" * 32):
    if components is None:
        ids = set()
        for kind, fact in facts:
            if kind == "commitment":
                ids.update(item["component_id"] for item in fact["component_commitments"])
            else:
                ids.update(fact["component_ids"])
        if not ids:
            raise AssertionError("Declare component facts explicitly for a no-entry manifest")
        components = [
            {"component_id": value, "makerspace_id": makerspace_id + index,
             "ciphertext_sha256": digest(f"slice:{value}")}
            for index, value in enumerate(sorted(ids))
        ]
    sequences = [
        {**fact, "constraint_identity": "", "definition_sha256": ""}
        for fact in sequence_facts("default")
    ]
    # A restored readable main really has installed/called high-water state.
    _install_sequence_high_water("default", sequences)
    manifest = {
        "artifact_id": str(uuid.uuid4()), "capture_id": str(uuid.uuid4()),
        "main_component": {"component_id": str(uuid.uuid4())},
        "slice_components": components,
        "not_restored_seeds": [
            {"component_id": item["component_id"],
             "makerspace_id": item["makerspace_id"], "state": "pending"}
            for item in components
        ],
        "source_partition_proof": {"fixture": "independently admitted source"},
        "reservation_salt": base64.b64encode(salt).decode(),
        "sequence_reservations": sequences,
        **{group: [] for group in GROUPS.values()},
    }
    for kind, fact in facts:
        manifest[GROUPS[kind]].append(fact)
    return manifest


def context(manifest):
    inputs = SimpleNamespace(
        run_id=uuid.uuid4(), artifact_sha256=digest("selected outer ciphertext"),
        capture_id=uuid.UUID(manifest["capture_id"]),
    )
    identity = SimpleNamespace(
        database_name="x07_sibling", database_oid=7001,
        durable_key=lambda: ("x07-server", "x07_sibling", 7001),
    )
    text, sha = compile_expectation(manifest, using="default")
    return SimpleNamespace(
        inputs=inputs, manifest=manifest, sibling=SimpleNamespace(identity=identity),
        text=text, sha=sha, expected=json.loads(text),
    )


def rehydrate(case):
    return rehydrate_pre_cutover_state(
        inputs=case.inputs, manifest=case.manifest, sibling=case.sibling,
    )


def prepared(facts, **kwargs):
    case = context(manifest_for(facts, **kwargs))
    rehydrate(case)
    return case


def operation_values(case):
    return {
        "operation_id": case.inputs.run_id,
        "artifact_id": case.manifest["artifact_id"],
        "capture_id": case.manifest["capture_id"],
        "main_component_id": case.manifest["main_component"]["component_id"],
        "outer_ciphertext_sha256": case.inputs.artifact_sha256,
        "outer_manifest_sha256": digest(case.manifest),
        "source_proof_sha256": digest(case.manifest["source_partition_proof"]),
        "sibling_database_name": "x07_sibling", "sibling_database_oid": 7001,
        "sibling_server_identity": digest(["x07-server", "x07_sibling", 7001]),
        "expected_installation": case.text, "expected_installation_sha256": case.sha,
    }


def operation(case):
    return B1RestoreOperationState.objects.get(pk=case.inputs.run_id)


def raw_stage(case, stage):
    sql("UPDATE public.backup_b1restoreoperationstate SET stage=%s "
        "WHERE operation_id=%s", [stage, case.inputs.run_id])


def raw_entry(case, expected, *, installed=True, verified=False, **overrides):
    values = {
        "operation_id": case.inputs.run_id, "component_id": expected["component_id"],
        "kind": expected["kind"], "registry_identity": expected["registry_identity"],
        "definition_sha256": expected["definition_sha256"],
        "safe_payload": expected["installed_payload"],
        "installed_at": timezone.now() if installed else None,
        "catalog_verified_at": timezone.now() if verified else None,
    }
    return B1ReservationEntry.objects.create(**{**values, **overrides})


def install_entries(case):
    for entry in case.expected["entries"]:
        install_reservation_entry(
            operation_id=case.inputs.run_id, component_id=entry["component_id"],
            kind=entry["kind"], fact=entry["source_fact"], expected_entry=entry,
            reservation_salt=case.manifest["reservation_salt"],
        )


def trigger_oid(table=TABLE):
    rows = sql(
        "SELECT oid, tgenabled, tgtype FROM pg_catalog.pg_trigger "
        "WHERE tgrelid=%s::regclass AND tgname='backup_b1_reservation_guard'",
        [f"public.{table}"],
    )
    assert len(rows) == 1 and rows[0][1] in ("O", "A") and rows[0][2] == 31
    return rows[0][0]


def finish_installation(case):
    from apps.backup.compound_restore_state import install_manifest_enforcement
    from apps.backup.compound_restore_target import DatabaseStateTarget

    install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)
    DatabaseStateTarget(using="default", acknowledgement=None).verify_catalog(
        case.sibling, case.inputs, case.manifest,
    )
    for stage in ("objects_verified", "quarantine_verified", "cutover_ready"):
        raw_stage(case, stage)
