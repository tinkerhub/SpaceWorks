"""Coherent signed artifacts and process adapters for real coordinator contracts.

No provider is launched. The real artifact/proof admission and coordinator run;
only catalog/build facts and process/database/object adapters are fixtures.
"""

import json
from pathlib import Path
import uuid

from apps.backup import import_preflight, outer_reservation_validation
from apps.backup.compound_restore_coordinator import run_compound_restore
from apps.backup.compound_restore_types import CompoundRestoreInputs
from tests.backup import e9b_coordinator_test_support as support
from tests.backup.import_preflight_test_support import (
    POSTGRES_MAJOR, SOURCE_HASH, make_import_fixture,
)


class Pointer(support.Pointer):
    def preflight(self, *, allow_committed_cutover=False):
        self.events.append("pointer-preflight")
        return super().preflight()


class Database(support.Database):
    def preflight(self):
        self.events.append("database-preflight")
        return super().preflight()

    def prove_sibling(self, sibling):
        sibling = super().prove_sibling(sibling)
        assert sibling.empty and sibling.non_routable and sibling.created_by_this_run
        self.events.append("non-routable-empty-sibling")
        return sibling

    def restore(self, sibling, path):
        assert sibling.non_routable and sibling.empty
        assert Path(path).read_bytes() == b"readable main database"
        super().restore(sibling, path)


class Artifact:
    def __init__(self, path):
        self.path = path

    def database_dump_path(self):
        return str(self.path)


def prepared_coordinator(monkeypatch, tmp_path):
    # Empty reservation facts match the shared fixture's empty source registry.
    # These read-only host/catalog inputs are the only admission substitutions.
    monkeypatch.setattr(import_preflight, "build_info", lambda: {"source_hash": SOURCE_HASH})
    monkeypatch.setattr(import_preflight, "server_major", lambda: POSTGRES_MAJOR)
    monkeypatch.setattr(outer_reservation_validation, "load_unique_rules", lambda: ())
    monkeypatch.setattr(outer_reservation_validation, "server_major", lambda: POSTGRES_MAJOR)
    fixture = make_import_fixture(tmp_path)
    for path in (fixture.encrypted, fixture.bundle, fixture.manifest_file, fixture.secrets_file):
        path.chmod(0o600)
    inputs = CompoundRestoreInputs(
        run_id=str(uuid.uuid4()), capture_id=fixture.manifest["capture_id"],
        artifact_sha256=fixture.expected_sha256,
        encrypted_file=str(fixture.encrypted), bundle=str(fixture.bundle),
        manifest_file=str(fixture.manifest_file),
        continuity_secrets_file=str(fixture.secrets_file),
        expected_sha256=fixture.expected_sha256,
    )
    events = []
    journal = support.Journal(events)
    arguments = dict(
        ops_dir=tmp_path / "ops", inputs=inputs,
        artifact=Artifact(fixture.root / "database.dump"),
        database=Database(events), writers=support.Writers(events),
        pointer=Pointer(events), target=support.Target(events),
        object_store=support.Objects(events), capability=support.Capability(),
        capability_journal=journal,
        marker_writer=support.MarkerWriter(tmp_path / "marker.json", journal, events),
        require_root_owned=False,
    )
    return fixture, arguments, events


def assert_no_effects(arguments, events, *, probes=()):
    assert events == list(probes)
    assert arguments["pointer"].current == "old"
    assert arguments["database"].sibling is None
    assert not arguments["writers"].excluded
    assert arguments["capability_journal"].armed is None
    assert not arguments["marker_writer"].marker_path.exists()
    assert not list(arguments["ops_dir"].glob("runs/*.jsonl"))


def assert_canonical_sibling_order(monkeypatch, tmp_path):
    fixture, arguments, events = prepared_coordinator(monkeypatch, tmp_path)
    result = run_compound_restore(**arguments)
    required = (
        "pointer-preflight", "database-preflight", "offline", "exclude",
        "allocate:1", "non-routable-empty-sibling", "database-restore",
        "roles-grants", "not-restored-and-reservations", "fences-installed",
        "catalog-verified", "object-write", "marker:candidate-health",
        "capability-armed", "candidate-backend-without-migrate",
        "candidate-readiness", "pointer-cutover", "acknowledgement",
        "marker:normal", "start:backend,worker,beat",
    )
    positions = [events.index(event) for event in required]
    assert positions == sorted(positions)
    assert arguments["pointer"].current == "new"
    assert arguments["database"].sibling.non_routable
    assert result["new_generation"] == 2
    ledger_path = arguments["ops_dir"] / "runs" / f"{arguments['inputs'].run_id}.jsonl"
    records = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    done = [record for record in records if record["state"] == "done"]
    from apps.backup.compound_restore_coordinator import PHASES

    assert tuple(record["phase"] for record in done) == PHASES
    cutover = next(record["detail"] for record in done if record["phase"] == "cutover")
    assert cutover["sibling_ownership_proof"]["non_routable"] is True
    assert cutover["sibling_ownership_proof"]["created_by_this_run"] is True
    assert cutover["grant_state"]["state"] == "candidate-preparation"
    assert fixture.manifest["capture_id"] == arguments["inputs"].capture_id
