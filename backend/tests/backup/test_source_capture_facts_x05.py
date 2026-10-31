"""Independent capture facts must precede signing and survive no input drift."""

from dataclasses import FrozenInstanceError
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.backup import outer_manifest, source_verifier
from apps.backup.errors import BackupBuildError
from apps.backup.source_capture_facts import (
    require_source_capture_facts,
    source_capture_facts_from_capture,
    source_capture_facts_from_mapping,
)
from tests.backup.e7_partition_test_helpers import (
    detailed_manifest, resign_manifest, signed_manifest, source_verifier_case,
)


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("shape", ["missing", "missing-field", "extra", "list", "null"])
def test_outer_rejects_malformed_independent_source_mapping(tmp_path, shape):
    manifest = signed_manifest(tmp_path)
    if shape == "missing":
        manifest.pop("source_capture")
    elif shape == "missing-field":
        manifest["source_capture"].pop("frozen_dump_sha256")
    elif shape == "extra":
        manifest["source_capture"]["producer_asserted"] = True
    elif shape == "list":
        manifest["source_capture"] = list(manifest["source_capture"].items())
    else:
        manifest["source_capture"] = None
    # Preserve a valid outer signature so structural refusal is exercised.
    with pytest.raises(BackupBuildError):
        outer_manifest.verify_outer_manifest(resign_manifest(manifest))


@pytest.mark.parametrize("field", ["source_database_identity", "source_server_identity"])
@pytest.mark.parametrize("value", [None, True, 16, "", " \t", "a\nb", "a\x00b", "x" * 513])
def test_capture_identity_rejects_wrong_types_and_empty_or_unsafe_names(tmp_path, field, value):
    capture, _ = source_verifier_case(tmp_path)
    mapping = capture.source_capture_facts.as_dict()
    mapping[field] = value
    with pytest.raises(BackupBuildError, match="identity is invalid"):
        source_capture_facts_from_mapping(mapping)


@pytest.mark.parametrize("field", ["frozen_dump_sha256", "frozen_population_ownership_digest"])
@pytest.mark.parametrize("value", [None, 1, "", "A" * 64, "0" * 63])
def test_capture_digest_rejects_wrong_types_and_noncanonical_hex(tmp_path, field, value):
    capture, _ = source_verifier_case(tmp_path)
    mapping = capture.source_capture_facts.as_dict()
    mapping[field] = value
    with pytest.raises(BackupBuildError, match="digest is invalid"):
        source_capture_facts_from_mapping(mapping)


@pytest.mark.parametrize("drift", ["database", "server", "dump", "population", "references"])
def test_source_verifier_refuses_frozen_input_drift_before_probe_or_signature(
    monkeypatch, tmp_path, drift,
):
    capture, reconstruction = source_verifier_case(tmp_path)
    if drift == "population":
        capture.frozen_population = ({"makerspace_id": 999},)
    elif drift == "references":
        capture.object_plan.references = (SimpleNamespace(
            bucket_kind="private", site="evidence", candidate_owner="main",
            canonical_makerspace_id=701, coordination_policy="tenant",
        ),)
    else:
        field = {"database": "source_database_identity", "server": "source_server_identity",
                 "dump": "source_dump_sha256"}[drift]
        setattr(capture, field, "f" * 64)
    probe, sign = Mock(), Mock()
    monkeypatch.setattr(source_verifier, "_verify_main_non_occupancy", probe)
    monkeypatch.setattr(source_verifier, "sign_bytes", sign)
    with pytest.raises(BackupBuildError, match="changed after freezing"):
        source_verifier.verify_and_sign_source_partition(
            capture, detailed_manifest=detailed_manifest(), reconstruction_pass=reconstruction,
        )
    probe.assert_not_called()
    sign.assert_not_called()


@pytest.mark.parametrize("frozen", [None, "mapping"])
def test_unsigned_capture_mapping_cannot_authorize_source_signing(monkeypatch, tmp_path, frozen):
    capture, reconstruction = source_verifier_case(tmp_path)
    capture.source_capture_facts = None if frozen is None else capture.source_capture_facts.as_dict()
    sign = Mock()
    monkeypatch.setattr(source_verifier, "sign_bytes", sign)
    with pytest.raises(BackupBuildError, match="facts are missing"):
        source_verifier.verify_and_sign_source_partition(
            capture, detailed_manifest=detailed_manifest(), reconstruction_pass=reconstruction,
        )
    sign.assert_not_called()


def test_source_mapping_without_detached_proof_signature_is_refused(tmp_path):
    manifest = signed_manifest(tmp_path)
    manifest["source_partition_proof"].pop("proof_signature")
    with pytest.raises(BackupBuildError):
        outer_manifest.verify_outer_manifest(resign_manifest(manifest))


def test_unicode_ownership_uses_the_existing_ascii_escaped_canonicalization(tmp_path):
    capture, _ = source_verifier_case(tmp_path)
    population = ({"makerspace_id": 701, "label": "കേന്ദ്രം"},)
    reference = SimpleNamespace(
        bucket_kind="private", site="evidence.é", candidate_owner="slice:701",
        canonical_makerspace_id=701, coordination_policy="tenant",
    )
    capture.frozen_population = population
    capture.object_plan.references = (reference,)
    facts = source_capture_facts_from_capture(capture)
    ownership = {"population": population, "references": [{
        "bucket_kind": "private", "site": "evidence.é", "candidate_owner": "slice:701",
        "makerspace_id": 701, "coordination_policy": "tenant",
    }]}
    ascii_digest = hashlib.sha256(json.dumps(
        ownership, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()
    utf8_digest = hashlib.sha256(json.dumps(
        ownership, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    assert facts.frozen_population_ownership_digest == ascii_digest
    assert ascii_digest != utf8_digest
    with pytest.raises(FrozenInstanceError):
        facts.source_database_identity = "replacement"


def test_correct_v2_source_verifier_to_outer_roundtrip(monkeypatch, tmp_path):
    capture, reconstruction = source_verifier_case(tmp_path)
    independent = capture.source_capture_facts.as_dict()
    monkeypatch.setattr(source_verifier, "_verify_main_non_occupancy", lambda _capture: None)
    detailed = detailed_manifest()
    capture.source_partition_proof = source_verifier.verify_and_sign_source_partition(
        capture, detailed_manifest=detailed, reconstruction_pass=reconstruction,
    )
    manifest = outer_manifest.build_outer_manifest(
        archive=capture.archive, capture=capture, detailed_manifest=detailed, root=tmp_path,
    )
    assert manifest["protocol_version"] == "spaceworks-lane-e-b1-v2"
    assert manifest["source_capture"] == independent
    mutable_copy = capture.source_capture_facts.as_dict()
    mutable_copy["source_database_identity"] = "changed-copy"
    assert capture.source_capture_facts.as_dict() == independent
    assert outer_manifest.verify_outer_manifest(manifest) is True
    assert require_source_capture_facts(capture).as_dict() == independent
