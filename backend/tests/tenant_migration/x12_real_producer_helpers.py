"""Real PG projection and age producer, with no DB/provider approval substitutes."""

import json
from pathlib import Path
import subprocess
import tarfile
from types import SimpleNamespace
from uuid import uuid4

from django.db import connection, connections, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.apiclients.models import ApiClient
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.deployment_keys import public_deployment_identity
from apps.tenant_migration.tenant_dump_api_clients import build_source_client_catalog
from apps.tenant_migration.tenant_dump_builder import build_tenant_dump
from apps.tenant_migration.tenant_dump_catalog import CATALOG_SCHEMA_SHA256
from apps.tenant_migration.tenant_dump_database import (
    dump_scratch_database, empty_verification_database, restore_scratch_dump,
)
from apps.tenant_migration.tenant_dump_envelope import build_tenant_content_ledger, seal_outer_bundle
from apps.tenant_migration.tenant_dump_inner_manifest import _manifest
from apps.tenant_migration.tenant_dump_lineage import derivation_policy_digest
from apps.tenant_migration.tenant_dump_outer_manifest_facts import compatibility_facts, recipient_fingerprint_facts
from apps.tenant_migration.tenant_dump_pii import scan_mapped_pii
from apps.tenant_migration.tenant_dump_projection_expectations import capture_projection_expectations
from apps.tenant_migration.tenant_dump_source_projection import project_makerspace_source
from apps.tenant_migration.tenant_restore_types import ArtifactPreflight, RestoreInputs
from tests.tenant_migration.x12_selected_test_helpers import private_write, sha


def freeze_client_source(root):
    """Dump real source rows, change live metadata, then read only the restored alias."""
    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    space = Makerspace.objects.create(name="X12 source", slug="x12-source", superadmin_access_enabled=False)
    other = Makerspace.objects.create(name="X12 foreign", slug="x12-foreign")
    own = []
    for label in ("Frozen active", "Frozen inactive", "Frozen invalid"):
        client, secret = ApiClient.issue(
            label=label, scopes=["public:read"], makerspace=space,
            allowed_origins=["https://source.example.test"], raw_secret=f"source-secret-{label}",
        )
        own.append((client, secret))
    ApiClient.objects.filter(pk=own[1][0].pk).update(is_active=False)
    ApiClient.objects.filter(pk=own[2][0].pk).update(scopes=["unknown:scope"])
    for owner, label in ((other, "Foreign excluded"), (None, "Global excluded")):
        ApiClient.issue(label=label, scopes=["public:read"], makerspace=owner,
                        allowed_origins=["https://foreign.example.test"], raw_secret="foreign-secret")
    identity = public_deployment_identity()
    image = root / "database.source.dump"
    dump_scratch_database(connection.settings_dict["NAME"], image)
    capture = SimpleNamespace(
        pk=uuid4(), source_makerspace_id=space.pk, source_makerspace_slug=space.slug,
        source_deployment_identity=identity, source_encryption_mode=False,
        catalog_digest=CATALOG_SCHEMA_SHA256, database_image_sha256=sha(image.read_bytes()),
        object_ledger_sha256=sha(b"[]"), requested_by_id=None, gate_owner_id=uuid4(),
        gate_fencing_token=1, superadmin_access_at_decision=False, frozen_tenant_recipients=[],
        database_snapshot_at=timezone.now(), capture_completed_at=timezone.now(), source_postgres_major=16,
    )
    # The producer must not accidentally consult these current live declarations.
    ApiClient.objects.filter(makerspace=space).update(label="Changed live row", allowed_origins=["https://live.example.test"])
    policy = derivation_policy_digest(source_encryption_mode=False)
    with empty_verification_database(space.pk, uuid4()) as (using, name):
        restore_scratch_dump(image, name)
        with transaction.atomic(using=using):
            with connections[using].cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            with CaptureQueriesContext(connections[using]) as queries:
                catalog = build_source_client_catalog(capture.pk, identity["deployment_id"], space.pk, using=using)
            query_sql = [item["sql"] for item in queries.captured_queries]
            projection = project_makerspace_source(space.pk, using=using, capture_id=capture.pk)
            expectations = capture_projection_expectations(
                projection, capture_id=capture.pk, source_database_image_sha256=capture.database_image_sha256,
                catalog_sha256=CATALOG_SCHEMA_SHA256, derivation_policy_sha256=policy, using=using,
            )
    return SimpleNamespace(root=root, space=space, own=own, capture=capture, catalog=catalog,
                           projection=projection, expectations=expectations, policy=policy, queries=query_sql)


def real_age_identity(root):
    """Invoke actual age binaries; absence/failure is an execution prerequisite failure."""
    identity = Path(root) / "custodian.agekey"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
    identity.chmod(0o600)
    recipient = subprocess.run(["age-keygen", "-y", str(identity)], check=True,
                               capture_output=True, text=True).stdout.strip()
    assert recipient.startswith("age1")
    return identity, recipient


def produce_encrypted_source(frozen):
    """Actual builder -> production inner builder -> actual age sealing -> decrypt."""
    root, capture = frozen.root, frozen.capture
    bundle = root / "bundle"
    bundle.mkdir(mode=0o700)
    build = build_tenant_dump(frozen.projection, bundle / "database.dump", run_id=capture.pk,
                             source_pii_mode="plaintext", expectations=frozen.expectations)
    findings = scan_mapped_pii(frozen.projection.rows, "plaintext")
    inner = _manifest(capture, build, (), frozen.projection, frozen.policy,
                      pii_mode="plaintext", pii_findings=findings, retained_keys=(),
                      key_envelope=None, api_client_catalog=frozen.catalog)
    inner["contents"] = build_tenant_content_ledger(bundle, source_pii_mode="plaintext")
    inner_bytes = json.dumps(inner, sort_keys=True, separators=(",", ":")).encode()
    private_write(bundle / "manifest.json", inner_bytes)
    identity, recipient = real_age_identity(root)
    fingerprints = recipient_fingerprint_facts((recipient,))
    path, digest = seal_outer_bundle(
        bundle, root / "selected.tar", (recipient,), artifact_id=capture.pk, capture_id=capture.pk,
        outer_recipient_fingerprints=fingerprints, tenant_dek_recipient_fingerprints=fingerprints,
        source_build=dict(source_hash="x12-repository-integration"), postgres_major=16,
        compatibility=compatibility_facts(capture, inner["contents"], frozen.policy, "plaintext"),
    )
    with tarfile.open(path, "r:") as wrapper:
        encrypted = private_write(root / "selected-payload.age", wrapper.extractfile("payload.age").read())
        outer = json.load(wrapper.extractfile("outer-manifest.json"))
    plaintext = root / "decrypted.tar"
    subprocess.run(["age", "--decrypt", "-i", str(identity), "-o", str(plaintext), str(encrypted)],
                   check=True, capture_output=True)
    plaintext.chmod(0o600)
    extracted = root / "admitted"
    extracted.mkdir(mode=0o700)
    with tarfile.open(plaintext, "r:") as archive:
        emitted = archive.extractfile("manifest.json").read()
        private_write(extracted / "manifest.json", emitted)
        private_write(extracted / "database.dump", archive.extractfile("database.dump").read())
    assert emitted == inner_bytes
    assert sha(emitted) == outer["compatibility"]["inner_manifest_sha256"]
    adapter = SimpleNamespace(
        selected_artifact_path=lambda _: path, inner_manifest_path=lambda _: extracted / "manifest.json",
        database_dump_path=lambda: extracted / "database.dump",
        static_preflight=lambda _: ArtifactPreflight(*([True] * 12)),
    )
    inputs = RestoreInputs(str(uuid4()), digest, str(capture.pk), "operator@example.test")
    adapter.inputs = inputs
    return SimpleNamespace(path=path, inputs=inputs, inner=inner, outer=outer, adapter=adapter,
                           identity=identity, emitted=emitted, bundle=bundle, extracted=extracted)
