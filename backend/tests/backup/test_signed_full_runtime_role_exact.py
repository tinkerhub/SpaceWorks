"""Whole signed full capture under a real non-owner LOGIN, then real restore.

Root supplies disposable PostgreSQL (owner with CREATEROLE/CREATEDB), matching
client tools, local MinIO buckets, and age/age-keygen. Root alone runs this test.
BUILD/OCI below are explicitly synthetic metadata, not deployed-image attestation.
SQL, source identity, exported snapshot, pg_dump, age, storage and restore are real.
"""

from pathlib import Path
import tarfile
import tempfile

import pytest
from django.apps import apps

from apps.backup import archive_builder, archive_payload
from apps.backup.digests import sha256_file
from apps.backup.full_bundle import verify_full_bundle, verify_full_root
from apps.backup.full_format import FULL_FORMAT
from apps.backup.main_projection_registry import OMITTED_OPERATIONAL_MODELS
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.backup.projection_databases import restore_dump, temporary_database
from apps.inventory.models import InventoryProduct
from tests.backup.full_backup_capture_helpers import archive, space
from tests.backup.full_backup_fixture_helpers import BUILD, OCI
from tests.backup.full_backup_roundtrip_helpers import age_keypair, decrypt, schema_counts
from tests.backup.full_backup_runtime_role_exact_helpers import (
    assert_runtime_session,
    isolated_runtime_login,
    observe_real_dump,
    source_facts_with_denied_control,
)
from tests.makerspaces.module_cleanup_support import privileged_restored_orphan_receipt
from tests.makerspaces.purge_test_support import receipt


pytestmark = pytest.mark.django_db(transaction=True)


def test_real_signed_full_capture_and_restore_use_exact_runtime_login(
    tmp_path, monkeypatch, settings, allow_projection_databases,
):
    # Seed domain and operational rows using the owner before any source reads.
    source_identity = DeploymentDatabaseIdentity.load()
    ordinary = space(superadmin_access_enabled=True)
    product = InventoryProduct.objects.create(
        makerspace=ordinary, name="Runtime login full capture", description="source remains unchanged",
        total_quantity=3, available_quantity=3,
    )
    receipt()
    privileged_restored_orphan_receipt()
    row = archive()
    expected_product = InventoryProduct.objects.values().get(pk=product.pk)
    expected_identity = DeploymentDatabaseIdentity.objects.values().get(pk=1)
    exact_labels = {
        "backup.DeploymentDatabaseIdentity", "makerspaces.PurgeReceipt", "makerspaces.ModulePurgeReceipt",
    }
    assert OMITTED_OPERATIONAL_MODELS == exact_labels
    omitted = [apps.get_model(label) for label in sorted(exact_labels)]
    expected_operational = {
        model._meta.label: list(model.objects.order_by("pk").values()) for model in omitted
    }
    assert all(expected_operational.values())

    build = None
    # Keep identities, decrypted secrets and extracted payloads in one workspace
    # that disappears on success and on every assertion/restore failure.
    with tempfile.TemporaryDirectory(prefix="runtime-full-", dir=tmp_path) as workspace:
        workspace = Path(workspace)
        try:
            identity, recipient = age_keypair(workspace)
            settings.BACKUP_AGE_RECIPIENT = recipient
            monkeypatch.setenv("SECRET_KEY", settings.SECRET_KEY)
            monkeypatch.setenv("AUDIT_MAC_MASTER_KEY", settings.AUDIT_MAC_MASTER_KEY)
            # Only provenance metadata is synthetic; no source or byte seams.
            monkeypatch.setenv("SPACEWORKS_OCI_DIGEST", OCI)
            monkeypatch.setattr(archive_payload, "_build_info", lambda: dict(BUILD))
            # Do not let ambient libpq service settings override the test login.
            for name in ("PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
                monkeypatch.delenv(name, raising=False)

            with isolated_runtime_login() as runtime_role:
                database_name, server = source_facts_with_denied_control(runtime_role)
                assert server["database_uuid"] == str(source_identity.database_uuid)
                with observe_real_dump(monkeypatch, runtime_role) as (snapshots, children):
                    build = archive_builder.build_archive(row)
                assert len(snapshots) == len(children) == 1
                assert_runtime_session(runtime_role)
                manifest = build.manifest
                assert manifest["format"] == FULL_FORMAT
                assert manifest["source_capture"]["database_identity"] == database_name
                assert manifest["source_capture"]["server_identity"] == server
                assert manifest["source_capture"]["server_identity"]["system_identifier"] is None

            # The context has closed runtime sessions, restored ALL owner configs,
            # and removed only its fresh role/grants before creating a scratch DB.
            assert manifest["omitted_operational_models"] == sorted(exact_labels)
            assert manifest["makerspace_sets"] == {
                "retained": [ordinary.pk], "readable_main": [ordinary.pk], "sovereign": [],
            }
            # Real bucket probes must succeed; unavailable storage cannot silently
            # turn this local-MinIO integration test into a quiescence-only test.
            assert manifest["storage"] == {
                "consistency": {"private": "versioned", "public_image": "versioned"}, "objects": [],
            }
            assert InventoryProduct.objects.values().get(pk=product.pk) == expected_product
            assert DeploymentDatabaseIdentity.objects.values().get(pk=1) == expected_identity
            assert {
                model._meta.label: list(model.objects.order_by("pk").values()) for model in omitted
            } == expected_operational

            plain, extracted = workspace / "decrypted.tar", workspace / "extracted"
            decrypt(build, identity, plain)
            original = Path(build.tempdir.name) / "bundle"
            verify_full_bundle(plain, manifest, original / "manifest.json", original / "keys/env.json")
            extracted.mkdir()
            with tarfile.open(plain) as bundle:
                bundle.extractall(extracted, filter="data")
            verify_full_root(extracted, manifest)
            dump = extracted / "database.dump"
            assert dump.read_bytes()[:5] == b"PGDMP"
            assert sha256_file(dump) == manifest["source_capture"]["dump_sha256"]
            assert sha256_file(build.encrypted) == build.archive_sha256
            with temporary_database("runtime_full") as (using, name):
                restore_dump(dump, name)
                assert InventoryProduct.objects.using(using).values().get(pk=product.pk) == expected_product
                assert schema_counts(using, omitted) == {label: 0 for label in exact_labels}
            assert InventoryProduct.objects.values().get(pk=product.pk) == expected_product
            assert DeploymentDatabaseIdentity.objects.values().get(pk=1) == expected_identity
            assert {
                model._meta.label: list(model.objects.order_by("pk").values()) for model in omitted
            } == expected_operational
        finally:
            if build is not None:
                build.tempdir.cleanup()
