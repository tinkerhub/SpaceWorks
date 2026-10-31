"""Run the actual orchestrator with selected files and observable provider boundaries."""

from dataclasses import replace
from pathlib import Path

from apps.backup.host_run_ledger import RunLedger
from apps.backup.host_supervisor import HostMarkerTransition
from apps.tenant_migration.tenant_restore_orchestrator import run_target_restore
from tests.tenant_migration import test_tenant_restore_order_d7 as ordered


class RestoreScenario:
    def __init__(self, root, artifact):
        self.root, self.artifact = Path(root), artifact
        self.ops = self.root / "ops"
        self.inputs = replace(artifact.inputs, run_id=ordered.RUN_ID)
        self.events = []
        self.writers = ordered.Writers(self.events, self.ops)
        self.database = ordered.Database(self.writers, self.events)
        self.pointer = ordered.Pointer(self.events)
        self.target = ordered.Target(self.pointer, self.events)
        self.objects = ordered.Objects()
        self.journal = ordered.Journal()
        self.marker = self.root / "marker.json"
        self.database.database_marker_matches = lambda _sibling, expected: expected == self.expected_marker()
        self.pointer.cutover_detail = lambda _sibling: dict(
            old_generation=1, new_generation=2, new_database_url="postgres:///candidate",
            new_database_marker=self.expected_marker(),
        )
        self.target.reissue_api_clients = self.forbidden_old_callback

    def expected_marker(self):
        return dict(database_uuid="target-uuid", run_id=self.inputs.run_id,
                    artifact_sha256=self.inputs.artifact_sha256, capture_id=self.inputs.capture_id)

    def forbidden_old_callback(self, *args, **kwargs):
        raise AssertionError("The old opaque API-client callback must never run")

    def run(self):
        return run_target_restore(
            ops_dir=self.ops, inputs=self.inputs, artifact=self.artifact,
            database=self.database, writers=self.writers, pointer=self.pointer,
            target=self.target, object_store=self.objects, destination_prefix="imports/run",
            capability_journal=self.journal,
            marker_writer=HostMarkerTransition(self.marker, self.journal, require_root_owned=False),
            require_root_owned=False,
        )

    @property
    def ledger_path(self):
        return self.ops / "runs" / f"{self.inputs.run_id}.jsonl"

    def ledger(self):
        return RunLedger(self.ledger_path, run_id=self.inputs.run_id,
                         artifact_sha256=self.inputs.artifact_sha256)

    def assert_before_effects(self):
        assert self.events == []
        assert not self.marker.exists()
        assert not self.ledger_path.exists() or self.ledger_path.read_bytes() == b""
        assert self.database.last is None
        assert not self.pointer.swapped
        assert not list(self.ops.glob(".tenant-restore-dump-*"))
