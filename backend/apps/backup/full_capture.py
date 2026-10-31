"""Choose deployment custody once, inside the exported PostgreSQL snapshot."""

import json
from pathlib import Path
import uuid

from django.db import connection

from apps.backup.compound_archive import CompoundCapture
from apps.backup.compound_recipients import predecessor_snapshot
from apps.backup.digests import sha256_file
from apps.backup.errors import BackupBuildError
from apps.backup.full_population import retained_population, run_facts, servable_cohort
from apps.backup.full_source_identity import capture_source_identity
from apps.backup.object_ownership import MAIN_COMPONENT
from apps.backup.not_restored import assert_deployment_fully_restored
from apps.backup.outer_manifest_facts import closure_digest_from_slice_ledgers, digest_json
from apps.backup.runtime_image_identity import require_runtime_image_digest


class DeploymentCapture:
    """Full custody has source binding, never a fabricated B1 projection proof."""

    def __init__(self, **kwargs):
        self._kwargs = {**kwargs, "platform_recipients": tuple(
            dict(item) for item in kwargs["platform_recipients"]
        )}
        self.archive = kwargs["archive"]
        self.root = Path(kwargs["root"])
        self.capture_id = uuid.uuid4()
        self._compound = None
        self._frozen = None
        self.is_full = False
        self.frozen_slices = ()
        self.object_plan = None
        self._selected = False
        self._prepared = False

    def __getattr__(self, name):
        if self._compound is not None:
            return getattr(self._compound, name)
        raise AttributeError(name)

    def select_from_snapshot(self):
        if self._selected:
            raise BackupBuildError("Deployment custody was already selected.")
        self._selected = True
        assert_deployment_fully_restored()
        population = retained_population()
        self.is_full = all(
            item["superadmin_access_enabled"] is True and item["activation_state"] == "on"
            for item in population
        )
        if not self.is_full:
            self._compound = CompoundCapture(**self._kwargs)
            return
        self._frozen = json.dumps({"oci_digest": require_runtime_image_digest()}, sort_keys=True)
        cohort = servable_cohort()
        run = run_facts(self.archive, cohort)
        database, server = capture_source_identity(connection.connection)
        self._frozen = json.dumps({
            **json.loads(self._frozen),
            **predecessor_snapshot(),
            "capture_id": str(self.capture_id),
            "retained": population,
            "servable_run_cohort": cohort,
            "run": run,
            "user_closure_digest": closure_digest_from_slice_ledgers(()),
            "source_database_identity": database,
            "source_server_identity": server,
        }, sort_keys=True)

    @property
    def oci_digest(self):
        """Read the admitted FULL identity, never a later process environment."""
        if not self.is_full or self._frozen is None:
            raise BackupBuildError("Full runtime image identity has not been frozen.")
        return json.loads(self._frozen)["oci_digest"]

    def prepare_from_snapshot(self):
        if self._prepared:
            raise BackupBuildError("Deployment capture was already prepared.")
        if not self._selected:
            raise BackupBuildError("Deployment custody must be selected before the source dump.")
        if not self.is_full:
            self._compound.prepare_from_snapshot()
            self.frozen_slices = self._compound.frozen_slices
        else:
            self._frozen = json.dumps({
                **json.loads(self._frozen),
                "source_dump_sha256": sha256_file(self.root / "database.dump"),
            }, sort_keys=True)
        self._prepared = True

    def capture_from_snapshot(self, **kwargs):
        if not self.is_full:
            return self._compound.capture_from_snapshot(**kwargs)
        if not self._prepared or self.object_plan is not None:
            raise BackupBuildError("Full capture was not prepared, or was already bound.")
        self.object_plan = kwargs["object_plan"]
        self.object_plan.assert_complete()
        # Freeze the exact typed source references, not a later manifest assertion.
        frozen = json.loads(self._frozen)
        ownership_digest = self._ownership_digest(frozen)
        self._frozen = json.dumps({**frozen, "object_ownership_digest": ownership_digest}, sort_keys=True)

    def _ownership_digest(self, frozen):
        return digest_json({
            "retained_population": frozen["retained"],
            "servable_run_cohort": frozen["servable_run_cohort"],
            "run": frozen["run"],
            "references": [vars(item) for item in self.object_plan.references],
        })

    def promotion_snapshot(self):
        if not self.is_full:
            return self._compound.promotion_snapshot()
        frozen = json.loads(self._frozen)
        if (
            not self._prepared or self.object_plan is None
            or frozen["capture_id"] != str(self.capture_id)
            or frozen.get("object_ownership_digest") != self._ownership_digest(frozen)
        ):
            raise BackupBuildError("The frozen full capture or source object references changed.")
        return frozen

    def project_readable_main(self, manifest):
        if not self.is_full:
            return self._compound.project_readable_main(manifest)
        frozen = self.promotion_snapshot()
        if sha256_file(self.root / "database.dump") != frozen["source_dump_sha256"]:
            raise BackupBuildError("The full source dump changed after capture.")
        if manifest["oci_digest"] != frozen["oci_digest"]:
            raise BackupBuildError("The full runtime image identity changed after capture.")
        self.object_plan.verify_component(MAIN_COMPONENT, manifest["storage"]["objects"])
        return {
            **manifest,
            "covered_makerspace_ids": [item["makerspace_id"] for item in frozen["retained"]],
        }

    def build_manifest(self, detailed_manifest):
        if self.is_full:
            from apps.backup.full_manifest import build_full_manifest

            if detailed_manifest["oci_digest"] != self.oci_digest:
                raise BackupBuildError("The full runtime image identity changed before signing.")
            return build_full_manifest(self, detailed_manifest)
        from apps.backup.outer_manifest import build_outer_manifest

        return build_outer_manifest(
            archive=self.archive, capture=self._compound,
            detailed_manifest=detailed_manifest, root=self.root,
        )

    def cleanup_verifier_material(self):
        if self._compound is not None:
            self._compound.cleanup_verifier_material()
