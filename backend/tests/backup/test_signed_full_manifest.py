"""Cryptographic domain, complete byte ledger and exact signed-full schema."""

from copy import deepcopy

import pytest

from apps.backup.errors import BackupBuildError
from apps.backup.full_manifest import verify_full_manifest
from apps.backup.main_projection_registry import OMITTED_OPERATIONAL_MODELS
from apps.backup.outer_manifest import SIGNATURE_DOMAIN, verify_outer_manifest
from apps.ed25519 import encode_key, generate_keypair
from tests.backup.full_backup_fixture_helpers import make_full_fixture, sign_manifest
from tests.backup.import_preflight_test_support import make_import_fixture


def test_real_ed25519_full_signature_and_exact_operational_registry(tmp_path):
    manifest = make_full_fixture(tmp_path).manifest
    assert verify_full_manifest(manifest) is True
    assert manifest["omitted_operational_models"] == sorted(OMITTED_OPERATIONAL_MODELS)
    assert manifest["source_capture"]["dump_sha256"] == manifest["main_component"]["ciphertext_sha256"]
    assert {item["path"] for item in manifest["contents"]} == {
        "database.dump", "keys/env.json", "objects/private/evidence/issue.jpg",
        "objects/public_image/inventory/tool.png",
    }
    with pytest.raises(BackupBuildError):
        verify_outer_manifest(manifest)


def test_b1_domain_cannot_authenticate_full_even_with_same_host_key(tmp_path):
    manifest = make_full_fixture(tmp_path).manifest
    with pytest.raises(BackupBuildError, match="signature"):
        verify_full_manifest(sign_manifest(manifest, domain=SIGNATURE_DOMAIN))


@pytest.mark.django_db
def test_actual_b1_signature_cannot_authenticate_full_payload(tmp_path):
    manifest = make_full_fixture(tmp_path).manifest
    b1 = make_import_fixture(tmp_path)
    manifest["archive_signature"] = b1.manifest["archive_signature"]
    with pytest.raises(BackupBuildError, match="signature"):
        verify_full_manifest(manifest)


def test_external_host_key_cannot_be_replaced_by_archived_self_trust(tmp_path, settings):
    manifest = make_full_fixture(tmp_path).manifest
    _private, other_public = generate_keypair()
    settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY = encode_key(other_public)
    with pytest.raises(BackupBuildError, match="does not match"):
        verify_full_manifest(manifest)
    manifest["verification_public_key"] = encode_key(other_public)
    with pytest.raises(BackupBuildError, match="schema"):
        verify_full_manifest(manifest)


@pytest.mark.parametrize("field,value", [
    ("algorithm", "rsa"), ("value", "not base64"), ("value", "AA=="),
    ("signer_fingerprint", "0" * 64), ("unknown", "injected"),
])
def test_signature_shape_algorithm_and_bytes_refuse(tmp_path, field, value):
    manifest = make_full_fixture(tmp_path).manifest
    manifest["archive_signature"][field] = value
    with pytest.raises(BackupBuildError):
        verify_full_manifest(manifest)


@pytest.mark.parametrize("field", [
    "archive_id", "capture_id", "backup_run_id", "contents", "source_capture",
    "settings", "omitted_operational_models", "archive_signature",
])
def test_missing_signed_fields_refuse(tmp_path, field):
    manifest = make_full_fixture(tmp_path).manifest
    del manifest[field]
    with pytest.raises(BackupBuildError):
        verify_full_manifest(manifest)


@pytest.mark.parametrize("field", ["artifact_id", "archive_id", "capture_id", "backup_run_id"])
def test_boolean_uuid_identifiers_refuse_even_with_valid_signature(tmp_path, field):
    manifest = make_full_fixture(tmp_path).manifest
    manifest[field] = True
    with pytest.raises(BackupBuildError, match="schema"):
        verify_full_manifest(sign_manifest(manifest))


@pytest.mark.parametrize("field", [
    "source_partition_proof", "reservation_manifest", "source_projection_catalog",
    "object_ledgers", "not_restored_seeds", "verification_public_key", "unknown",
])
def test_signed_b1_only_or_unknown_claims_refuse(tmp_path, field):
    manifest = make_full_fixture(tmp_path).manifest
    manifest[field] = {}
    with pytest.raises(BackupBuildError, match="schema"):
        verify_full_manifest(sign_manifest(manifest))


@pytest.mark.parametrize("change", [
    "bool-id", "bool-size", "bool-pg", "bool-port", "bool-object-owner",
    "main-bool-size", "dump-digest", "operational-empty", "operational-extra",
    "noncanonical-id", "source-version", "source-database", "wrong-case-path",
])
def test_signed_structural_inconsistency_refuses(tmp_path, change):
    manifest = make_full_fixture(tmp_path).manifest
    if change == "bool-id":
        manifest["covered_makerspace_ids"] = [True]
        manifest["makerspace_sets"] = {"retained": [True], "readable_main": [True], "sovereign": []}
    elif change == "bool-size":
        manifest["contents"][0]["size"] = True
    elif change == "bool-pg":
        manifest["postgres"]["source_server_major"] = True
    elif change == "bool-port":
        manifest["source_capture"]["server_identity"]["endpoint"]["port"] = True
    elif change == "bool-object-owner":
        manifest["storage"]["objects"][0]["makerspace_id"] = True
    elif change == "main-bool-size":
        manifest["main_component"]["size_bytes"] = True
    elif change == "dump-digest":
        manifest["source_capture"]["dump_sha256"] = "f" * 64
    elif change.startswith("operational"):
        manifest["omitted_operational_models"] = [] if change.endswith("empty") else [
            *manifest["omitted_operational_models"], "accounts.User",
        ]
    elif change == "noncanonical-id":
        manifest["archive_id"] = manifest["archive_id"].upper()
    elif change == "source-version":
        manifest["source_capture"]["server_identity"]["server_version_num"] = "170004"
    elif change == "source-database":
        manifest["source_capture"]["database_identity"] = "other"
    else:
        manifest["contents"][0]["path"] = "Database.dump"
    with pytest.raises(BackupBuildError, match="schema"):
        verify_full_manifest(sign_manifest(manifest))


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_every_content_ledger_member_is_signed(tmp_path, index):
    manifest = deepcopy(make_full_fixture(tmp_path).manifest)
    manifest["contents"][index]["sha256"] = "f" * 64
    with pytest.raises(BackupBuildError):
        verify_full_manifest(manifest)
