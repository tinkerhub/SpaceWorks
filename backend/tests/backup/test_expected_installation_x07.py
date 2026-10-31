"""Immutable canonical contract and independently compiled source expectations."""

from copy import deepcopy
import hashlib
import json
import uuid

import pytest
from django.db import DatabaseError, transaction

from apps.backup.compound_restore_expectation import canonical_text, compile_expectation
from apps.backup.models import B1RestoreOperationState
from apps.backup.recipient_selection import BackupBuildError
from tests.backup.x07_assertion_test_helpers import changed, snapshot
from tests.backup.x07_installation_test_helpers import (
    context, fence, installation_tables, manifest_for, operation, operation_values,
    prepared, raw_entry, rehydrate, sql,
)


pytestmark = pytest.mark.django_db(transaction=True)


def test_python_and_sql_reproduce_exact_utf8_text_and_sha_before_retained_rows(
    installation_tables,
):
    case = context(manifest_for([("broad_fence", fence([uuid.uuid4()]))]))
    assert not B1RestoreOperationState.objects.filter(pk=case.inputs.run_id).exists()
    assert "étiquette" in case.text and "\\u00e9" not in case.text
    assert case.text == json.dumps(
        case.expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    expected_sha = hashlib.sha256(case.text.encode("utf-8")).hexdigest()
    assert case.sha == expected_sha
    [(text, sha)] = sql(
        "SELECT public.backup_b1_canonical_json(%s::jsonb), "
        "encode(sha256(convert_to(%s, 'UTF8')), 'hex')", [case.text, case.text],
    )
    assert text.encode("utf-8") == case.text.encode("utf-8")
    assert sha == expected_sha
    rehydrate(case)
    assert operation(case).expected_installation == case.text
    assert operation(case).expected_installation_sha256 == expected_sha
    actual = sql(
        "SELECT public.backup_b1_expected_inventory(o) FROM "
        "public.backup_b1restoreoperationstate o WHERE operation_id=%s",
        [case.inputs.run_id],
    )[0][0]
    assert (json.loads(actual) if isinstance(actual, str) else actual) == case.expected


SHAPE_CASES = (
    "version-string", "version-bool", "version-float", "version-future",
    "unknown-root", "missing-root", "empty-components", "component-extra",
    "component-duplicate", "component-bool-space", "component-string-space",
    "component-uppercase-uuid", "component-bad-digest", "manifest-binding",
    "entry-extra", "entry-duplicate", "entry-unknown-component", "entry-kind",
    "entry-bool-oid", "entry-string-oid", "entry-stale-relation",
    "entry-wrong-function", "source-identity", "source-definition",
    "source-extra", "source-duplicate-components", "compiled-extra",
    "sequence-duplicate", "sequence-bool-increment", "sequence-extra",
)


def _malformed(expected, case):
    value = deepcopy(expected)
    component = value["components"][0]
    entry = value["entries"][0]
    if case.startswith("version-"):
        value["version"] = {"string": "1", "bool": True, "float": 1.0, "future": 2}[
            case.removeprefix("version-")
        ]
    elif case == "unknown-root": value["extra"] = {}
    elif case == "missing-root": del value["sequences"]
    elif case == "empty-components": value["components"] = []
    elif case == "component-extra": component["extra"] = 1
    elif case == "component-duplicate": value["components"].append(deepcopy(component))
    elif case == "component-bool-space": component["makerspace_id"] = True
    elif case == "component-string-space": component["makerspace_id"] = "7001"
    elif case == "component-uppercase-uuid": component["component_id"] = component["component_id"].upper()
    elif case == "component-bad-digest": component["ciphertext_sha256"] = "z" * 64
    elif case == "manifest-binding": value["manifest_sha256"] = "0" * 64
    elif case == "entry-extra": entry["extra"] = "untrusted"
    elif case == "entry-duplicate": value["entries"].append(deepcopy(entry))
    elif case == "entry-unknown-component": entry["component_id"] = str(uuid.uuid4())
    elif case == "entry-kind": entry["kind"] = "numeric_range"
    elif case == "entry-bool-oid": entry["target_relation_oid"] = True
    elif case == "entry-string-oid": entry["target_relation_oid"] = str(entry["target_relation_oid"])
    elif case == "entry-stale-relation": entry["target_relation_oid"] = 1
    elif case == "entry-wrong-function": entry["enforcement_function_oid"] = 1
    elif case == "source-identity": entry["source_fact"]["constraint_identity"] = "0" * 64
    elif case == "source-definition": entry["source_fact"]["definition_sha256"] = "0" * 64
    elif case == "source-extra":
        entry["source_fact"]["arbitrary"] = True
        entry["installed_payload"]["arbitrary"] = True
    elif case == "source-duplicate-components":
        entry["source_fact"]["component_ids"] *= 2
        entry["installed_payload"]["component_ids"] *= 2
    elif case == "compiled-extra": entry["installed_payload"]["arbitrary"] = True
    elif case == "sequence-duplicate": value["sequences"].append(deepcopy(value["sequences"][0]))
    elif case == "sequence-bool-increment": value["sequences"][0]["increment"] = True
    elif case == "sequence-extra": value["sequences"][0]["arbitrary"] = True
    else: raise AssertionError(case)
    return value


@pytest.mark.parametrize("defect", SHAPE_CASES)
def test_sql_insert_requires_exact_version_shape_types_and_source_binding(
    installation_tables, defect,
):
    case = context(manifest_for([("broad_fence", fence([
        uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    ]))]))
    assert case.expected["entries"] and case.expected["sequences"]
    values = operation_values(case)
    text = canonical_text(_malformed(case.expected, defect))
    values.update(expected_installation=text,
                  expected_installation_sha256=hashlib.sha256(text.encode()).hexdigest())
    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreOperationState.objects.create(**values)
    assert not B1RestoreOperationState.objects.filter(pk=case.inputs.run_id).exists()


@pytest.mark.parametrize("defect", ("whitespace", "wrong-hash", "duplicate-json-key"))
def test_sql_checks_stored_text_bytes_instead_of_jsonb_reserialization(
    installation_tables, defect,
):
    case = context(manifest_for([("broad_fence", fence([uuid.uuid4()]))]))
    values = operation_values(case)
    if defect == "whitespace": values["expected_installation"] = json.dumps(case.expected)
    elif defect == "duplicate-json-key":
        values["expected_installation"] = case.text[:-1] + ',"version":1}'
    else: values["expected_installation_sha256"] = "0" * 64
    if defect != "wrong-hash":
        values["expected_installation_sha256"] = hashlib.sha256(
            values["expected_installation"].encode(),
        ).hexdigest()
    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreOperationState.objects.create(**values)


@pytest.mark.parametrize("field", ("text", "sha", "both"))
def test_expected_text_and_digest_are_immutable_from_insert(installation_tables, field):
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    updates = {}
    if field in ("text", "both"): updates["expected_installation"] = case.text + " "
    if field in ("sha", "both"):
        updates["expected_installation_sha256"] = hashlib.sha256((case.text + " ").encode()).hexdigest()
    with pytest.raises(DatabaseError, match="immutable from INSERT"), transaction.atomic():
        B1RestoreOperationState.objects.filter(pk=case.inputs.run_id).update(**updates)
    assert operation(case).expected_installation == case.text
    assert operation(case).expected_installation_sha256 == case.sha


@pytest.mark.parametrize("drift", ("manifest", "component", "source", "compiled"))
def test_resume_recompiles_independent_manifest_facts_and_rejects_drift(
    installation_tables, drift,
):
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    assert rehydrate(case)["persistent"] is True
    before = snapshot(case)
    if drift == "compiled":
        # The expected OID must reproduce even when a relation keeps its name.
        sql("ALTER TABLE backup_x07_probe RENAME TO backup_x07_old_probe")
        sql("CREATE TABLE backup_x07_probe (LIKE backup_x07_old_probe INCLUDING ALL)")
    else:
        path, replacement = {
            "manifest": (("source_partition_proof", "fixture"), "another source"),
            "component": (("slice_components", 0, "ciphertext_sha256"), "0" * 64),
            "source": (("broad_fence_scopes", 0, "operations"), ["insert"]),
        }[drift]
        case.manifest = changed(case.manifest, path, replacement)
        if drift == "source":
            from tests.backup.x07_installation_test_helpers import seal_fence
            case.manifest["broad_fence_scopes"][0] = seal_fence(case.manifest["broad_fence_scopes"][0])
    try:
        with pytest.raises(BackupBuildError, match="changed|another identity"):
            rehydrate(case)
        assert snapshot(case) == before
    finally:
        if drift == "compiled":
            sql("DROP TABLE backup_x07_probe CASCADE")
            sql("ALTER TABLE backup_x07_old_probe RENAME TO backup_x07_probe")


def test_compiler_never_learns_expectations_from_retained_reservations(installation_tables):
    case = prepared([("broad_fence", fence([uuid.uuid4()]))])
    raw_entry(case, case.expected["entries"][0], installed=False,
              safe_payload={"untrusted_retained_row": True})
    assert compile_expectation(case.manifest, using="default") == (case.text, case.sha)
    assert operation(case).expected_installation == case.text
