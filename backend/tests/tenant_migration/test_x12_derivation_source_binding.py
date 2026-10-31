"""Actual derivation controller must capture catalog through its immutable alias."""

import json
import subprocess
import tarfile
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.apiclients.models import ApiClient
from apps.backup.models import MakerspaceArchiveRecipient
from apps.backup.recipients import fingerprint_for
from apps.tenant_migration.models import TenantDumpCapture
from apps.tenant_migration.tenant_dump_capture import canonical_tenant_recipient_snapshot
from apps.tenant_migration.tenant_dump_derivation import derive_tenant_dump
from apps.tenant_migration.tenant_dump_lineage import derivation_policy_digest
from apps.tenant_migration.tenant_dump_outer_artifact import read_outer_manifest
from apps.tenant_migration.tenant_dump_staging import create_capture_root
from apps.tenant_migration.tenant_restore_artifact_admission import read_selected_artifact_context
from apps.tenant_migration.tenant_restore_types import RestoreInputs
from tests.tenant_migration.x12_real_producer_helpers import freeze_client_source, real_age_identity
from tests.tenant_migration.x12_selected_test_helpers import private_write, sha

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("allow_projection_databases")]


def test_actual_derivation_embeds_immutable_catalog_in_age_output_with_live_rows_changed(tmp_path, settings):
    settings.PII_ENCRYPTION_ENABLED = False
    settings.BACKUP_AGE_RECIPIENT = ""
    settings.TENANT_DUMP_STAGING_DIR = str(tmp_path / "staging")
    frozen = freeze_client_source(tmp_path / "source")
    identities = []
    for index in range(2):
        key_root = tmp_path / f"custodian-{index}"
        key_root.mkdir(mode=0o700)
        identity, recipient = real_age_identity(key_root)
        identities.append(identity)
        MakerspaceArchiveRecipient.objects.create(
            makerspace=frozen.space, public_recipient=recipient, fingerprint=fingerprint_for(recipient),
            label=f"X12 custodian {index}", verified_at=timezone.now(),
        )
    actor = User.objects.create_user(username="x12-derivation-operator", email="operator@example.test",
                                     role=User.Role.SUPERADMIN, is_superuser=True)
    facts = frozen.capture
    # Phase S fixture: a real pg_dump image plus explicit captured metadata.
    # No active DB, custody predicate, projection verifier or encryption call is replaced.
    capture = TenantDumpCapture.objects.create(
        id=facts.pk, makerspace=frozen.space, requested_by=actor, status=TenantDumpCapture.Status.CAPTURED,
        source_deployment_identity=facts.source_deployment_identity,
        source_makerspace_id=facts.source_makerspace_id, source_makerspace_slug=facts.source_makerspace_slug,
        superadmin_access_at_decision=False,
        frozen_tenant_recipients=list(canonical_tenant_recipient_snapshot(frozen.space.pk)),
        gate_owner_id=facts.gate_owner_id, gate_fencing_token=1,
        database_snapshot_at=facts.database_snapshot_at, capture_completed_at=facts.capture_completed_at,
        source_postgres_major=16, database_image_sha256=facts.database_image_sha256,
        object_ledger=[], object_ledger_sha256=facts.object_ledger_sha256,
        source_encryption_mode=False, catalog_digest=facts.catalog_digest,
    )
    root = create_capture_root(capture.pk)
    private_write(root / "database.source.dump", (frozen.root / "database.source.dump").read_bytes())
    assert set(ApiClient.objects.filter(makerspace=frozen.space).values_list("label", flat=True)) == {"Changed live row"}
    artifact, manifest = derive_tenant_dump(capture.pk)
    # JSONField persistence and emitted JSON normalize nested tuples to arrays.
    expected_manifest = json.loads(json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ))
    capture.refresh_from_db()
    assert capture.status == TenantDumpCapture.Status.PENDING_PUBLICATION
    assert capture.manifest == expected_manifest
    assert manifest["api_client_catalog"] == frozen.catalog
    assert {entry["label"] for entry in manifest["api_client_catalog"]["entries"]} == {
        "Frozen active", "Frozen inactive", "Frozen invalid",
    }
    assert manifest["source"]["deployment_identity"] == facts.source_deployment_identity
    assert manifest["api_client_catalog"]["source_deployment_id"] == facts.source_deployment_identity["deployment_id"]
    assert capture.derivation_policy_sha256 == derivation_policy_digest(source_encryption_mode=False)
    outer = read_outer_manifest(artifact, expected_artifact_sha256=sha(artifact.read_bytes()))
    assert outer["version"] == 2
    with tarfile.open(artifact, "r:") as wrapper:
        payload = private_write(root / "roundtrip.age", wrapper.extractfile("payload.age").read())
    plaintext = root / "roundtrip.tar"
    subprocess.run(["age", "--decrypt", "-i", str(identities[0]), "-o", str(plaintext), str(payload)],
                   check=True, capture_output=True)
    with tarfile.open(plaintext, "r:") as archive:
        emitted = archive.extractfile("manifest.json").read()
    assert json.loads(emitted) == expected_manifest
    assert sha(emitted) == outer["compatibility"]["inner_manifest_sha256"]
    private_write(root / "authenticated-manifest.json", emitted)
    class Adapter:
        def selected_artifact_path(self, _):
            return artifact
        def inner_manifest_path(self, _):
            return root / "authenticated-manifest.json"
    inputs = RestoreInputs(str(uuid4()), sha(artifact.read_bytes()), str(capture.pk), actor.email)
    context = read_selected_artifact_context(inputs, Adapter())
    assert context.api_client_catalog["sha256"] == frozen.catalog["sha256"]
    assert context.projection_proof_sha256 == manifest["projection_verification"]["sha256"]
    assert not (root / "derived").exists()
    for forbidden in (b"Frozen active", b"source.example.test", b"source-secret"):
        assert forbidden not in artifact.read_bytes()
