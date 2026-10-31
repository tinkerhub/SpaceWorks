"""Actual age subprocess roundtrips prove the emitted manifest-buffer binding."""

import json
import subprocess
import tarfile

import pytest

from apps.tenant_migration import tenant_dump_envelope as producer
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_restore_artifact_admission import read_selected_artifact_context
from apps.tenant_migration.tenant_restore_types import RestoreInputs
from tests.tenant_migration.x12_real_producer_helpers import real_age_identity
from tests.tenant_migration.x12_selected_test_helpers import DUMP, admission_inner, outer_manifest, private_write, sha


def bundle_for(root, inner=None):
    root.mkdir(mode=0o700)
    private_write(root / "database.dump", DUMP)
    inner = inner if inner is not None else admission_inner()
    private_write(root / "manifest.json", json.dumps(inner, sort_keys=True, separators=(",", ":")).encode())
    return inner


def seal(bundle, output, inner, recipient="fixture-recipient", *, compatibility=None):
    compatibility = compatibility if compatibility is not None else outer_manifest(inner)["compatibility"]
    # The production producer derives this independently, as derivation callers do.
    compatibility = {key: value for key, value in compatibility.items() if key != "inner_manifest_sha256"}
    return producer.seal_outer_bundle(
        bundle, output, (recipient,), artifact_id=inner["capture_id"], capture_id=inner["capture_id"],
        outer_recipient_fingerprints=["fixture-recipient"], tenant_dek_recipient_fingerprints=["fixture-recipient"],
        source_build={"source_hash": "age-buffer-regression"}, postgres_major=16, compatibility=compatibility,
    )


def test_real_age_decrypted_member_is_exact_frozen_buffer_even_after_path_changes(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    inner = bundle_for(tmp_path / "bundle")
    bundle = tmp_path / "bundle"
    expected = (bundle / "manifest.json").read_bytes()
    identity, recipient = real_age_identity(tmp_path)
    actual_popen = subprocess.Popen
    observed = []
    def change_path_after_freeze(*args, **kwargs):
        observed.append(True)
        private_write(bundle / "manifest.json", b'{"replacement":"not the frozen bytes"}')
        return actual_popen(*args, **kwargs)
    monkeypatch.setattr(producer.subprocess, "Popen", change_path_after_freeze)
    path, digest = seal(bundle, tmp_path / "selected.tar", inner, recipient)
    # Restore the constructor before decrypting; only the producer race is injected.
    monkeypatch.setattr(producer.subprocess, "Popen", actual_popen)
    assert observed == [True]
    outer = producer.read_outer_manifest(path, expected_artifact_sha256=digest)
    assert outer["version"] == 2
    with tarfile.open(path, "r:") as wrapper:
        payload = private_write(tmp_path / "ciphertext.age", wrapper.extractfile("payload.age").read())
    decrypted = tmp_path / "decrypted.tar"
    subprocess.run(["age", "--decrypt", "-i", str(identity), "-o", str(decrypted), str(payload)],
                   check=True, capture_output=True)
    with tarfile.open(decrypted, "r:") as archive:
        emitted = archive.extractfile("manifest.json").read()
    assert emitted == expected
    assert sha(emitted) == outer["compatibility"]["inner_manifest_sha256"]
    assert emitted != (bundle / "manifest.json").read_bytes()
    private_write(bundle / "manifest.json", emitted)
    class Adapter:
        def selected_artifact_path(self, _):
            return path
        def inner_manifest_path(self, _):
            return bundle / "manifest.json"
    inputs = RestoreInputs(inner["capture_id"], digest, inner["capture_id"], "operator@example.test")
    context = read_selected_artifact_context(inputs, Adapter())
    assert context.inner_manifest_sha256 == sha(expected)
    assert context.projection_mode == "verified_v1"
    assert context.api_client_catalog["sha256"] == inner["api_client_catalog"]["sha256"]


@pytest.mark.parametrize("case", ["proof_absent", "catalog_absent", "capture", "content", "custody"])
def test_new_producer_refuses_missing_or_incompatible_admission_facts_before_age(tmp_path, monkeypatch, case):
    inner = admission_inner()
    if case == "proof_absent":
        inner.pop("projection_verification")
    elif case == "catalog_absent":
        inner.pop("api_client_catalog")
    elif case == "capture":
        inner["projection_verification"]["capture_id"] = "00000000-0000-0000-0000-000000000001"
    elif case == "content":
        inner["contents"][0]["sha256"] = "f" * 64
    else:
        inner["source_pii_mode"] = "encrypted"
    bundle = tmp_path / "bundle"
    bundle_for(bundle, inner)
    monkeypatch.setattr(producer.subprocess, "Popen", lambda *a, **k: pytest.fail("invalid producer reached age"))
    with pytest.raises(TenantDumpVerificationError):
        seal(bundle, tmp_path / "refused.tar", inner)
    assert not (tmp_path / "refused.tar").exists()


def test_producer_refuses_conflicting_precomputed_inner_hash(tmp_path, monkeypatch):
    inner = bundle_for(tmp_path / "bundle")
    compatibility = outer_manifest(inner)["compatibility"]
    compatibility["inner_manifest_sha256"] = "f" * 64
    monkeypatch.setattr(producer.subprocess, "Popen", lambda *a, **k: pytest.fail("conflicting digest reached age"))
    with pytest.raises(TenantDumpVerificationError, match="digest changed"):
        producer.seal_outer_bundle(
            tmp_path / "bundle", tmp_path / "refused.tar", ("fixture-recipient",),
            artifact_id=inner["capture_id"], capture_id=inner["capture_id"],
            outer_recipient_fingerprints=["fixture-recipient"], tenant_dek_recipient_fingerprints=["fixture-recipient"],
            source_build={"source_hash": "test"}, postgres_major=16, compatibility=compatibility,
        )
