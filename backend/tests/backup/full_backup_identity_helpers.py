"""Typed target facts and real marker files; no archived identity adoption."""

from copy import deepcopy
import json
import uuid

from apps.backup.full_format import FULL_FORMAT


def target_record():
    identifier = str(uuid.uuid4())
    return {
        "format": FULL_FORMAT,
        "identity": {"name": "stage3_target", "oid": 12345, "server_identity": {
            "endpoint": {"host": "target-db", "port": 5432, "database": "stage3_target", "tls_identity": ""},
            "database_uuid": identifier, "system_identifier": None,
        }},
        "row": {"id": 1, "database_uuid": identifier, "run_id": str(uuid.uuid4()),
                "artifact_sha256": "a" * 64, "capture_id": str(uuid.uuid4()),
                "created_at": "2026-10-29T01:02:03.123456+00:00"},
    }


def marker_payload(record, *, state="normal"):
    identity = record["identity"]
    return {
        "version": 2, "state": state,
        "database": {"binding": "bound", "name": identity["name"], "oid": identity["oid"],
                     "routing": "non-routable-sibling" if state.startswith("candidate") else "active",
                     "server_identity": deepcopy(identity["server_identity"])},
        "readiness": {"reservations": [], "fences": [], "not_restored": []},
    }


def write_marker(tmp_path, record, *, state="normal"):
    path = tmp_path / "host-marker.json"
    path.write_text(json.dumps(marker_payload(record, state=state)))
    path.chmod(0o444)
    return path
