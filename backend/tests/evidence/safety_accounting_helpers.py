"""Actual portable reference projection/import; no host restore is implied."""
from copy import deepcopy

from django.db import connection

from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.backup.raw_projection import raw_records
from apps.data_export.reference_provenance import ReferenceProvenanceWriter
from apps.evidence import storage
from apps.evidence.finalization import finalize_upload
from apps.evidence.models import EvidencePhoto, EvidenceUploadFinalization
from apps.tenant_migration.archive_stream import PortableArchive
from apps.tenant_migration.pk_maps import TransactionPkMap
from apps.tenant_migration.raw_repository import RawImportRepository
from apps.tenant_migration.reference_state import ReferenceState
from apps.tenant_migration.semantic_remap import remap_semantic_references
from tests.atomic_publication.store import png
from tests.evidence.safety_access_helpers import photo


def snapshot_copy(value):
    """Copy full raw rows, preserving PostgreSQL binary fields as exact bytes."""
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, dict):
        return {key: snapshot_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(snapshot_copy(item) for item in value)
    return deepcopy(value)


def project_marker(marker, root):
    writer = ReferenceProvenanceWriter(root, marker.makerspace_id)
    try:
        writer.prepare_rows("audit.AuditLog", [marker])
        row = raw_records(AuditLog.objects.filter(pk=marker.pk), AuditLog)[0]
        for name in ("target_type", "target_id", "meta"):
            row[name] = writer.project(marker, name, row[name])
    finally:
        writer.close()
    # EvidencePhoto is a remappable target; no source-only target snapshot is emitted.
    assert (root / "migration/reference_provenance.jsonl").read_text() == ""
    (root / "migration/external_references.jsonl").write_text("")
    return row


def import_projected_marker(source, root, target_photo):
    """Persist a final imported AuditLog through the real temporary PK map/repository."""
    pk_map = TransactionPkMap()
    pk_map.add_many(EvidencePhoto, [(source["target_id"], target_photo.pk)])
    pk_map.reserve(AuditLog, [source["id"]])
    references = ReferenceState(PortableArchive(root))
    assert references.count() == 0
    row = snapshot_copy(source)
    row.update(
        id=pk_map.lookup(AuditLog, source["id"]), makerspace_id=target_photo.makerspace_id,
        event_uuid=None, row_mac=None,
    )
    assert remap_semantic_references("audit.AuditLog", source, row, pk_map, references)
    assert RawImportRepository().insert_rows(AuditLog, [row]) == 1
    return AuditLog.objects.get(pk=row["id"])


def transplanted_journal(lab, source_state, target):
    """Adversarial copied journal, never a positive actual-debit proof."""
    lab.store.seed(storage.staging_key(target.object_key), png(), "image/png")
    result = finalize_upload(target, 1024 * 1024)
    assert result.size == len(png())
    read_keys = {args["Key"] for name, args in lab.store.calls if name == "get"}
    assert {target.object_key, storage.staging_key(target.object_key)} <= read_keys
    EvidenceUploadFinalization.objects.filter(evidence=target).update(
        quota_charged=True, updated_at=source_state.updated_at,
    )
    return EvidenceUploadFinalization.objects.get(evidence=target)


def fresh_target_photo(lab):
    return photo(lab, makerspace=lab.other)


def clear_identity():
    """Fixture-only database setup: TRUNCATE mirrors transactional test flush."""
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE TABLE backup_deploymentdatabaseidentity")


def seed_target_identity():
    clear_identity()
    return DeploymentDatabaseIdentity.objects.create(pk=1)
