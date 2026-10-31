"""EVID-S03 portability/provenance contracts, not an executed host restore artifact."""
from copy import deepcopy
import uuid

import pytest
from django.db import transaction

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.backup.raw_projection import raw_records
from apps.data_export.models import MODELS
from apps.data_export.types import OmittedModel
from apps.evidence import storage
from apps.evidence.finalization import charge_storage_once, finalize_upload
from apps.evidence.models import EvidencePhoto, EvidenceUploadFinalization
from apps.evidence.quota import local_accounting_database_id, proven_charge_bytes
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.audit_reference_guards import (
    discover_audit_meta_references, validate_audit_meta_references,
)
from apps.tenant_migration.audit_references import (
    AUDIT_META_REFERENCES, AUDIT_TARGET_DISPOSITIONS, AuditReferenceDisposition,
)
from apps.tenant_migration.reference_guards import ReferenceRegistryError, validate_audit_target_references
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from apps.tenant_migration.tenant_dump_raw import sanitize_record
from apps.tenant_migration.tenant_dump_semantic_expectations import (
    extract_semantic_references, verify_semantic_references,
)
from apps.tenant_migration.tenant_dump_source_projection import project_makerspace_source
from apps.tenant_migration.tenant_dump_types import ModelDisposition
from tests.atomic_publication.store import png
from tests.evidence.safety_access_helpers import charged_photo, photo, safety_lab
from tests.evidence.safety_accounting_helpers import (
    clear_identity, fresh_target_photo, import_projected_marker, project_marker,
    seed_target_identity, snapshot_copy, transplanted_journal,
)


pytestmark = pytest.mark.django_db(transaction=True)
EDGE = ("evidence.storage_charged", "accounting_database_id")


@pytest.fixture
def lab(monkeypatch, settings):
    return safety_lab(monkeypatch, settings)


def test_literal_accounting_identity_reference_is_source_local_and_guarded():
    discovery = discover_audit_meta_references()
    assert EDGE in discovery.id_paths
    assert AUDIT_META_REFERENCES[EDGE].disposition is AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT
    validate_audit_meta_references(discovery=discovery)
    missing = dict(AUDIT_META_REFERENCES)
    del missing[EDGE]
    with pytest.raises(ReferenceRegistryError, match="accounting_database_id"):
        validate_audit_meta_references(missing, discovery=discovery)
    validate_audit_target_references()
    target = AUDIT_TARGET_DISPOSITIONS["evidence.evidencephoto"]
    assert target.disposition is AuditReferenceDisposition.REMAP
    assert target.target_model_label == "evidence.EvidencePhoto"


@pytest.mark.parametrize("carry_journal", [False, True], ids=["omitted-journal", "copied-journal"])
def test_portable_projection_remaps_photo_but_namespaces_charge_identity(lab, tmp_path, carry_journal):
    evidence, state, marker = charged_photo(lab)
    projected = project_marker(marker, tmp_path)
    assert projected["target_id"] == str(evidence.pk)
    assert projected["meta"] == marker.meta | {
        "accounting_database_id": f"source:{lab.identity.database_uuid}",
    }
    assert type(projected["meta"]["bytes"]) is int
    assert type(projected["meta"]["version"]) is int
    target = fresh_target_photo(lab)
    target_state = transplanted_journal(lab, state, target) if carry_journal else None

    with transaction.atomic():
        imported = import_projected_marker(projected, tmp_path, target)

    assert target.pk != evidence.pk
    assert (imported.target_type, imported.target_id, imported.makerspace_id) == (
        "evidence.evidencephoto", str(target.pk), lab.other.pk,
    )
    assert imported.actor_id is None
    assert imported.meta == projected["meta"]
    assert proven_charge_bytes(target, target_state) == 0
    assert proven_charge_bytes(evidence, state) == len(png())
    if not carry_journal:
        assert not EvidenceUploadFinalization.objects.filter(evidence=target).exists()
    lab.other.refresh_from_db()
    assert lab.other.storage_bytes_used == 0


def test_custom_tenant_dump_retains_inert_snapshot_without_portable_prefix(lab):
    evidence, state, marker = charged_photo(lab)
    projection = project_makerspace_source(lab.home.pk)
    for label in ("evidence.EvidenceUploadFinalization", "backup.DeploymentDatabaseIdentity"):
        assert isinstance(MODELS[label], OmittedModel)
        assert FIRST_PARTY_MODEL_RULES[label].disposition is ModelDisposition.DROP
        assert label not in projection.rows
    source = next(row for row in projection.rows["audit.AuditLog"] if row["id"] == marker.pk)
    sanitized = sanitize_record(AuditLog, source)
    assert sanitized.values["meta"] == marker.meta
    assert sanitized.values["target_id"] == str(evidence.pk)
    assert sanitized.values["meta"]["accounting_database_id"] == str(lab.identity.database_uuid)
    assert sanitized.values["row_mac"] is None and sanitized.values["event_uuid"] is None
    rows = {"audit.AuditLog": [dict(sanitized.values)]}
    expected = extract_semantic_references(rows, expected=True)
    assert {item["location"] for item in expected} == {"json:meta", "target_type+target_id"}
    verify_semantic_references(rows, expected, resolved_pks={})

    target_identity = seed_target_identity()

    assert target_identity.database_uuid != lab.identity.database_uuid
    assert proven_charge_bytes(evidence, None) == 0  # normal omitted journal
    assert proven_charge_bytes(evidence, state) == 0  # even an adversarial retained journal
    assert AuditLog.objects.get(pk=marker.pk).meta == marker.meta


def test_consistent_local_database_snapshot_metadata_retains_proof(lab):
    evidence, state, marker = charged_photo(lab)
    lab.home.refresh_from_db()
    # These are raw DB snapshot records, not a portable archive or host restore run.
    models = (DeploymentDatabaseIdentity, EvidencePhoto, EvidenceUploadFinalization, AuditLog, Makerspace)
    snapshot = {model._meta.label: snapshot_copy(raw_records(model.objects.all(), model))
                for model in models}
    identity = snapshot["backup.DeploymentDatabaseIdentity"][0]
    finalization = snapshot["evidence.EvidenceUploadFinalization"][0]
    saved_marker = next(row for row in snapshot["audit.AuditLog"] if row["id"] == marker.pk)
    saved_space = next(row for row in snapshot["makerspaces.Makerspace"] if row["id"] == lab.home.pk)
    assert identity["database_uuid"] == lab.identity.database_uuid
    assert saved_marker["meta"] == marker.meta
    assert finalization["updated_at"].isoformat() == marker.meta["journal_version"]
    assert finalization["quota_charged"] is True
    assert finalization["size_bytes"] == saved_space["storage_bytes_used"] == len(png())
    assert proven_charge_bytes(evidence, state) == len(png())
    # Changing only the deployment identity makes the otherwise identical proof inert.
    seed_target_identity()
    assert proven_charge_bytes(evidence, state) == 0


def test_missing_identity_is_read_only_and_late_seed_cannot_retroactively_prove_debit(lab):
    evidence = photo(lab)
    lab.store.seed(storage.staging_key(evidence.object_key), png(), "image/png")
    result = finalize_upload(evidence, 1024 * 1024)
    clear_identity()
    assert local_accounting_database_id() is None

    charge_storage_once(evidence, result.size)
    charge_storage_once(evidence, result.size)

    state = EvidenceUploadFinalization.objects.get(evidence=evidence)
    marker = AuditLog.objects.get(action="evidence.storage_charged", target_id=str(evidence.pk))
    assert marker.meta["accounting_database_id"] is None
    assert proven_charge_bytes(evidence, state) == 0
    assert not DeploymentDatabaseIdentity.objects.exists()
    lab.home.refresh_from_db()
    assert lab.home.storage_bytes_used == len(png())
    DeploymentDatabaseIdentity.objects.create(pk=1)
    assert proven_charge_bytes(evidence, state) == 0


@pytest.mark.parametrize("database_id", ["not-a-uuid", str(uuid.UUID(int=17))])
def test_malformed_or_unknown_identity_marker_cannot_prove_target_debit(lab, database_id):
    evidence, state, _ = charged_photo(lab)
    target = fresh_target_photo(lab)
    target_state = transplanted_journal(lab, state, target)
    meta = {"version": 1, "bytes": state.size_bytes, "journal_version": state.updated_at.isoformat(),
            "accounting_database_id": database_id}
    audit.record(None, "evidence.storage_charged", makerspace=lab.other, target=target, meta=deepcopy(meta))
    assert proven_charge_bytes(target, target_state) == 0
    assert proven_charge_bytes(evidence, state) == len(png())
