"""Fixed identity input grammar and pre-insert authority checks, without Django."""

from dataclasses import replace
from io import StringIO
import json
from types import SimpleNamespace
import uuid

import pytest

from apps.backup.database_identity import DatabaseEndpoint, DatabaseIdentityError, LiveDatabaseIdentity
from apps.backup import full_restore_identity as identity
from tests.backup.full_backup_identity_helpers import marker_payload, target_record, write_marker


@pytest.mark.parametrize("change", [
    "missing", "format", "bool-oid", "bool-id", "uuid", "lineage", "timestamp", "extra",
    "endpoint", "system", "row-uuid",
])
def test_target_identity_record_requires_exact_typed_target_facts(change):
    record = target_record()
    if change == "missing":
        record.pop("row")
    elif change == "format":
        record["format"] = "spaceworks-phase5a-v3"
    elif change == "bool-oid":
        record["identity"]["oid"] = True
    elif change == "bool-id":
        record["row"]["id"] = True
    elif change == "uuid":
        record["row"]["database_uuid"] = "not-a-uuid"
    elif change == "lineage":
        record["row"]["capture_id"] = None
    elif change == "timestamp":
        record["row"]["created_at"] = "2026-10-29T01:02:03+00:00"
    elif change == "extra":
        record["row"]["source_authority"] = True
    elif change == "endpoint":
        record["identity"]["server_identity"]["endpoint"]["host"] = "postgres://user:secret@db"
    elif change == "system":
        record["identity"]["server_identity"]["system_identifier"] = "fabricated"
    else:
        record["row"]["database_uuid"] = str(uuid.uuid4())
    with pytest.raises(DatabaseIdentityError):
        identity.validate_target_record(record)


def test_private_input_accepts_only_bounded_identity_projection_and_unique_keys():
    record = target_record()
    encoded = json.dumps({"full_target_identity": record})
    assert identity.read_private_control(StringIO(encoded)) == {"full_target_identity": record}
    oversized = target_record()
    oversized["identity"]["server_identity"]["endpoint"]["host"] = "x" * identity.MAX_CONTROL_BYTES
    for raw in (
        encoded[:-1] + ', "restore_diff": {}}',
        '{"full_target_identity":null,"full_target_identity":' + json.dumps(record) + '}',
        " " * (identity.MAX_CONTROL_BYTES + 1) + encoded,
        json.dumps({"full_target_identity": oversized}),
        "{}",
    ):
        with pytest.raises(DatabaseIdentityError):
            identity.read_private_control(StringIO(raw))


@pytest.mark.parametrize("state", ["candidate-preparation", "candidate-health", "quarantined-after-cutover"])
def test_nonready_marker_refuses_before_any_database_effect(tmp_path, monkeypatch, state):
    record = target_record()
    marker = write_marker(tmp_path, record, state=state)
    # Only local test-file ownership is relaxed; parsing/identity/state checks run.
    monkeypatch.setattr("apps.backup.host_marker._assert_trusted_file", lambda _path: None)
    database = SimpleNamespace(autocommit=False)
    with pytest.raises(DatabaseIdentityError):
        identity.restore_target_identity(database, {"full_target_identity": record}, marker)


def test_unbound_intent_marker_cannot_authorize_target_identity_insertion(tmp_path, monkeypatch):
    record = target_record()
    payload = marker_payload(record, state="candidate-preparation")
    payload["database"] = {"binding": "intent"}
    payload["operation"] = {"restore_id": str(uuid.uuid4()), "artifact_sha256": "a" * 64,
                            "capture_id": str(uuid.uuid4()), "pointer_generation": 1}
    marker = tmp_path / "intent.json"
    marker.write_text(json.dumps(payload))
    marker.chmod(0o444)
    monkeypatch.setattr("apps.backup.host_marker._assert_trusted_file", lambda _path: None)
    with pytest.raises(DatabaseIdentityError):
        identity.restore_target_identity(SimpleNamespace(autocommit=False), {"full_target_identity": record}, marker)


@pytest.mark.parametrize("change", ["uuid", "oid", "name", "host", "tls"])
def test_root_marker_mismatch_refuses_before_any_database_effect(tmp_path, monkeypatch, change):
    record = target_record()
    marker = write_marker(tmp_path, record)
    monkeypatch.setattr("apps.backup.host_marker._assert_trusted_file", lambda _path: None)
    if change == "uuid":
        record["row"]["database_uuid"] = str(uuid.uuid4())
        record["identity"]["server_identity"]["database_uuid"] = record["row"]["database_uuid"]
    elif change == "oid":
        record["identity"]["oid"] += 1
    elif change == "name":
        record["identity"]["name"] = "other_target"
        record["identity"]["server_identity"]["endpoint"]["database"] = "other_target"
    else:
        key = "host" if change == "host" else "tls_identity"
        record["identity"]["server_identity"]["endpoint"][key] = (
            "other-host" if key == "host" else "verify-full:sha256:" + "c" * 64
        )
    with pytest.raises(DatabaseIdentityError):
        identity.restore_target_identity(SimpleNamespace(autocommit=False), {"full_target_identity": record}, marker)


def test_optional_system_corroboration_availability_may_differ_but_actual_values_may_not():
    record = target_record()
    server, row = record["identity"]["server_identity"], record["row"]
    live = LiveDatabaseIdentity(DatabaseEndpoint(**server["endpoint"]), record["identity"]["oid"],
                                row["database_uuid"], "123456789", row["run_id"],
                                row["artifact_sha256"], row["capture_id"])
    identity._compare_live(live, record)
    server["system_identifier"] = "123456789"
    identity._compare_live(replace(live, system_identifier=None), record)
    with pytest.raises(DatabaseIdentityError):
        identity._compare_live(replace(live, system_identifier="987654321"), record)
