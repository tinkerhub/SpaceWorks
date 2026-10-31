"""Frozen synthetic OCI syntax binds real signed FULL metadata, not image attestation."""

from copy import deepcopy
import json

import pytest
from django.db import connection

from apps.backup.errors import BackupBuildError
from apps.backup.full_bundle import verify_full_root
from apps.backup.full_manifest import verify_full_manifest
from apps.backup.full_manifest_validation import validate_full_manifest
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from tests.backup.full_backup_capture_helpers import space
from tests.backup.full_backup_fixture_helpers import OCI
from tests.backup.runtime_image_capture_support import captured_full_payload


pytestmark = pytest.mark.django_db(transaction=True)
OTHER_OCI = "sha256:" + "e" * 64


@pytest.mark.parametrize("later_digest", [None, "invalid-later-env", OTHER_OCI],
                         ids=["removed", "malformed", "different-valid"])
def test_full_payload_freezes_admitted_identity_and_signs_real_metadata(
    tmp_path, monkeypatch, later_digest,
):
    ordinary = space()
    value, detailed = captured_full_payload(tmp_path, monkeypatch, later_digest=later_digest)
    frozen = value.promotion_snapshot()
    assert value.oci_digest == frozen["oci_digest"] == detailed["oci_digest"] == OCI
    assert frozen["source_database_identity"] == connection.settings_dict["NAME"]
    assert frozen["source_server_identity"]["database_uuid"] == str(
        DeploymentDatabaseIdentity.objects.get(pk=1).database_uuid
    )
    manifest = value.build_manifest(detailed)
    assert manifest["oci_digest"] == manifest["build_identity"]["oci_digest"] == OCI
    assert manifest["covered_makerspace_ids"] == [ordinary.pk]
    assert manifest["source_capture"]["server_identity"] == frozen["source_server_identity"]
    assert verify_full_manifest(manifest) is True
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    verify_full_root(tmp_path, manifest)
    # The snapshot accessor returns independent values; a consumer cannot rebind it.
    frozen["oci_digest"] = OTHER_OCI
    assert value.promotion_snapshot()["oci_digest"] == OCI


@pytest.mark.parametrize("boundary", ["projection", "signing"])
def test_explicit_full_manifest_digest_substitution_is_refused(tmp_path, monkeypatch, boundary):
    space()
    value, detailed = captured_full_payload(tmp_path, monkeypatch)
    substituted = {**detailed, "oci_digest": OTHER_OCI}
    operation = value.project_readable_main if boundary == "projection" else value.build_manifest
    with pytest.raises(BackupBuildError, match="runtime image identity changed"):
        operation(substituted)
    assert value.oci_digest == OCI
    assert verify_full_manifest(value.build_manifest(detailed)) is True


def test_signed_runtime_identity_cannot_be_rebound_with_matching_schema(tmp_path, monkeypatch):
    space()
    value, detailed = captured_full_payload(tmp_path, monkeypatch)
    signed = value.build_manifest(detailed)
    tampered = deepcopy(signed)
    tampered["oci_digest"] = tampered["build_identity"]["oci_digest"] = OTHER_OCI
    unsigned = {key: item for key, item in tampered.items() if key != "archive_signature"}
    # Both digest fields agree and the genuine closed schema accepts that shape;
    # the unchanged signature must still reject the substituted identity.
    validate_full_manifest(unsigned)
    with pytest.raises(BackupBuildError, match="signature is invalid"):
        verify_full_manifest(tampered)
    assert verify_full_manifest(signed) is True
