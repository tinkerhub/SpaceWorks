"""Real pg_dump -> age -> decrypted artifact -> pg_restore, with local S3 bytes.

Requires the parent's disposable PG16/MinIO stack and age/age-keygen. No skips,
mocked dump/encryption/storage, elevated application role or restore evidence shortcuts.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import tarfile
import uuid

import pytest
from django.apps import apps
from django.db import connections, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.backup import archive_builder, archive_payload, full_restore_identity, host_readiness, storage
from apps.backup.database_identity import DatabaseIdentityError, establish_restored_database_identity
from apps.backup.full_bundle import verify_full_bundle, verify_full_root
from apps.backup.full_format import FULL_FORMAT
from apps.backup.full_source_identity import capture_source_identity
from apps.backup.errors import BackupBuildError
from apps.backup.main_projection_registry import OMITTED_OPERATIONAL_MODELS
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.backup.projection_databases import restore_dump, temporary_database
from apps.evidence.models import EvidencePhoto
from apps.inventory.models import InventoryProduct
from apps.object_storage import delete_all_versions
from tests.backup.full_backup_capture_helpers import archive, space
from tests.backup.full_backup_bootstrap_helpers import assert_bootstrap_grant_rollback
from tests.backup.full_backup_fixture_helpers import BUILD, OCI, sha
from tests.backup.full_backup_identity_helpers import write_marker
from tests.backup.full_backup_race_helpers import independent_job
from tests.backup.full_backup_roundtrip_helpers import age_keypair, clean_restore, decrypt, raw_row, schema_counts
from tests.makerspaces.module_cleanup_support import privileged_restored_orphan_receipt
from tests.makerspaces.purge_test_support import receipt


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("ready_state", ["normal", "acknowledged-normal"])
def test_real_full_artifact_operational_omission_target_identity_and_live_bytes(
    tmp_path, monkeypatch, settings, allow_projection_databases, ready_state,
):
    source_identity = DeploymentDatabaseIdentity.load()
    ordinary = space()
    actor = User.objects.create_superuser(username="full-roundtrip", password="unused")
    prefix = f"stage3-full-{uuid.uuid4().hex}"
    private_key, public_key = f"{prefix}/issue.jpg", f"{prefix}/tool.png"
    product = InventoryProduct.objects.create(makerspace=ordinary, name="Full roundtrip tool",
                                               description="snapshot-original", total_quantity=3,
                                               available_quantity=3, image_key=public_key)
    photo = EvidencePhoto.objects.create(makerspace=ordinary, evidence_type="issue",
                                          object_key=private_key, uploaded_by=actor)
    purge, module_purge = receipt(), privileged_restored_orphan_receipt()
    omitted = [apps.get_model(label) for label in sorted(OMITTED_OPERATIONAL_MODELS)]
    source_counts = {model._meta.label: model.objects.count() for model in omitted}
    assert all(source_counts.values())
    identity, recipient = age_keypair(tmp_path)
    settings.BACKUP_AGE_RECIPIENT = recipient
    monkeypatch.setenv("SPACEWORKS_OCI_DIGEST", OCI)
    monkeypatch.setenv("SECRET_KEY", settings.SECRET_KEY)
    monkeypatch.setenv("AUDIT_MAC_MASTER_KEY", settings.AUDIT_MAC_MASTER_KEY)
    expected_continuity = {name: os.environ.get(name, "") for name in archive_payload.CONTINUITY_KEYS}
    monkeypatch.setattr(archive_payload, "_build_info", lambda: dict(BUILD))
    # The archive builder uses its imported payload function, which reads this seam.
    s3 = storage.client()
    objects = [(settings.AWS_STORAGE_BUCKET_NAME, private_key, b"live-private-issue-bytes"),
               (settings.PUBLIC_IMAGE_BUCKET, public_key, b"live-public-image-bytes")]
    build = None
    try:
        expires = timezone.now().replace(microsecond=0) + timedelta(days=1)
        for bucket, key, payload in objects:
            s3.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="application/octet-stream", Expires=expires)
        expected_product = InventoryProduct.objects.values().get(pk=product.pk)
        real_dump, snapshots = archive_payload._pg_dump, []

        def observed_dump(destination, snapshot_id, **kwargs):
            assert kwargs == {"exclude_operational": True}
            snapshots.append(snapshot_id)
            # Commit after exported snapshot, before actual pg_dump. Its bytes
            # must contain the old row although source now has the new one.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(independent_job, lambda: InventoryProduct.objects.filter(pk=product.pk).update(
                    description="committed-after-export",
                )).result(timeout=10)
            return real_dump(destination, snapshot_id, **kwargs)

        monkeypatch.setattr(archive_payload, "_pg_dump", observed_dump)
        build = archive_builder.build_archive(archive())
        assert len(snapshots) == 1
        assert build.manifest["format"] == FULL_FORMAT
        assert build.manifest["omitted_operational_models"] == sorted(OMITTED_OPERATIONAL_MODELS)
        assert str(source_identity.database_uuid) == build.manifest["source_capture"]["server_identity"]["database_uuid"]
        plain, extracted = tmp_path / "decrypted.tar", tmp_path / "decrypted"
        decrypt(build, identity, plain)
        extracted.mkdir()
        # First authenticate tar, then extract only the regular, declared payload.
        original = Path(build.tempdir.name) / "bundle"
        verify_full_bundle(plain, build.manifest, original / "manifest.json", original / "keys/env.json")
        with tarfile.open(plain) as bundle:
            bundle.extractall(extracted, filter="data")
        verify_full_root(extracted, build.manifest)
        assert json.loads((extracted / "keys/env.json").read_bytes()) == expected_continuity
        for bucket, key, payload in objects:
            kind = "private" if bucket == settings.AWS_STORAGE_BUCKET_NAME else "public_image"
            assert (extracted / "objects" / kind / key).read_bytes() == payload
            fact = next(item for item in build.manifest["storage"]["objects"]
                        if item["key"] == key and item["bucket_kind"] == kind)
            assert fact["headers"]["Expires"] == str(expires)
        assert sha((extracted / "database.dump").read_bytes()) == build.manifest["source_capture"]["dump_sha256"]
        assert InventoryProduct.objects.get(pk=product.pk).description == "committed-after-export"
        assert {model._meta.label: model.objects.count() for model in omitted} == source_counts
        assert DeploymentDatabaseIdentity.objects.get(pk=1).database_uuid == source_identity.database_uuid
        with temporary_database("full_stage3") as (using, name):
            restore_dump(extracted / "database.dump", name)
            assert schema_counts(using, omitted) == {model._meta.label: 0 for model in omitted}
            with pytest.raises(BackupBuildError, match="identity is unavailable"):
                capture_source_identity(connections[using].connection)
            assert InventoryProduct.objects.using(using).values().get(pk=product.pk) == expected_product
            assert EvidencePhoto.objects.using(using).get(pk=photo.pk).object_key == private_key
            target = establish_restored_database_identity(run_id=uuid.uuid4(), artifact_sha256="b" * 64,
                                                          capture_id=uuid.uuid4(), using=using)
            assert target.database_uuid != source_identity.database_uuid
            database = connections[using]
            with transaction.atomic(using=using):
                captured = full_restore_identity.capture_target_identity(database.connection)
            marker = write_marker(tmp_path, captured, state=ready_state)
            marker_bytes = marker.read_bytes()
            monkeypatch.setattr("apps.backup.host_marker._assert_trusted_file", lambda _path: None)
            # Real clean restore removes the target singleton via schema replacement;
            # it cannot import the omitted source identity or purge authority.
            clean_restore(extracted / "database.dump", name)
            with pytest.raises(DatabaseIdentityError):
                full_restore_identity.verify_target_identity(database.connection, captured)
            # An available but different physical target fact refuses without insertion.
            changed = deepcopy(captured)
            changed["identity"]["oid"] += 1
            spoof_dir = tmp_path / "spoofed-physical-target"
            spoof_dir.mkdir()
            spoof_marker = write_marker(spoof_dir, changed, state=ready_state)
            with pytest.raises(DatabaseIdentityError), transaction.atomic(using=using):
                full_restore_identity.restore_target_identity(database.connection, {"full_target_identity": changed}, spoof_marker)
            assert raw_row(database.connection) == []
            # Run the actual fixed maintenance bootstrap: identity, role guards,
            # and grants all execute on its real connection before an injected
            # final grant failure. Identity and role creation must both roll back.
            from django.db import connection
            runtime_role = "stage3_bootstrap_" + uuid.uuid4().hex
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", [runtime_role])
                assert cursor.fetchone() is None
            assert_bootstrap_grant_rollback(monkeypatch, database, captured, marker, runtime_role)
            assert raw_row(database.connection) == []
            assert marker.read_bytes() == marker_bytes
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", [runtime_role])
                assert cursor.fetchone() is None
            # An unexpected source row cannot be adopted or silently overwritten.
            DeploymentDatabaseIdentity.objects.using(using).create(pk=1, database_uuid=source_identity.database_uuid)
            with pytest.raises(DatabaseIdentityError), transaction.atomic(using=using):
                full_restore_identity.restore_target_identity(database.connection, {"full_target_identity": captured}, marker)
            clean_restore(extracted / "database.dump", name)
            with transaction.atomic(using=using):
                full_restore_identity.restore_target_identity(database.connection, {"full_target_identity": captured}, marker)
                assert full_restore_identity.capture_target_identity(database.connection) == captured
            with pytest.raises(DatabaseIdentityError), transaction.atomic(using=using):
                full_restore_identity.restore_target_identity(database.connection, {"full_target_identity": captured}, marker)
            monkeypatch.setattr(host_readiness, "connection", database)
            assert host_readiness.assert_host_ready(marker)["marker_state"] == ready_state
            assert marker.read_bytes() == marker_bytes
            assert schema_counts(using, omitted) == {model._meta.label: int(model == DeploymentDatabaseIdentity) for model in omitted}
    finally:
        if build is not None:
            build.tempdir.cleanup()
        for bucket, key, _payload in objects:
            delete_all_versions(s3, bucket=bucket, key=key)
