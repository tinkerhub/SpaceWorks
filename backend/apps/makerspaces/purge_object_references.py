"""Coordination references missing from the canonical backup object field set."""

from dataclasses import dataclass

from django.apps import apps


@dataclass(frozen=True)
class CoordinationReference:
    kind: str
    key: str
    owner: int | None
    site: str
    delete_owned: bool = True


# Field-specific ownership; source locators are references, not deletion authority.
# Locator authority is inert and deliberately excluded from active-reference proof.
INERT_RECEIPT_FIELDS = frozenset({
    ("makerspaces.ModulePurgeReceipt", "storage_origins"),
    ("makerspaces.ModulePurgeReceipt", "exact_keys"),
    ("makerspaces.ModulePurgeReceipt", "namespace_clauses"),
    ("makerspaces.ModulePurgeReceipt", "holder_sites"),
    ("makerspaces.ModulePurgeReceipt", "charge_obligations"),
    ("makerspaces.ModulePurgeReceipt", "rollback_bindings"),
    ("makerspaces.PurgeReceipt", "exact_keys"),
    ("makerspaces.PurgeReceipt", "namespace_prefixes"),
    ("makerspaces.PurgeReceipt", "storage_origins"),
})

COORDINATION_FIELDS = (
    ("admin_api.BulkImportJob", "upload", "private", "makerspace_id", True),
    ("tenant_migration.TenantImportObject", "staging_key", "private", "job__target_makerspace_id", True),
    ("tenant_migration.TenantImportObject", "target_key", "bucket_kind", "job__target_makerspace_id", True),
    ("tenant_migration.TenantImportObject", "source_key", "bucket_kind", "job__target_makerspace_id", False),
    ("backup.RestoreRollbackObject", "source_key", "bucket_kind", "makerspace_id", False),
    ("backup.BackupArchive", "staging_object_key", "private", None, False),
    ("tenant_migration.TenantDumpCapture", "unpublished_object_key", "private", None, False),
    # Deployment-owned artifact journal survives tenant deletion. A match refuses
    # rather than destroying a byte still addressed by recovery/reconciliation.
    ("backup.BackupArtifactLedger", "staging_locator", "private", None, False),
    ("backup.BackupArtifactLedger", "final_locator", "private", None, False),
)


def validate_coordination_registry():
    for label, field in INERT_RECEIPT_FIELDS:
        model_field = apps.get_model(label)._meta.get_field(field)
        if model_field.get_internal_type() != "JSONField":
            from apps.makerspaces.purge_storage import PurgeStorageRefused

            raise PurgeStorageRefused("Inert purge receipt locator classification drifted.")
    names = {"source_key", "target_key", "staging_key", "staging_object_key",
             "unpublished_object_key", "staging_locator", "final_locator", "upload"}
    actual = {(model._meta.label, field.name) for model in apps.get_models()
              for field in model._meta.concrete_fields if field.name in names}
    declared = {(label, field) for label, field, *_ in COORDINATION_FIELDS}
    if actual != declared:
        from apps.makerspaces.purge_storage import PurgeStorageRefused

        raise PurgeStorageRefused("Purge coordination object-reference registry has drifted.")


def coordination_references():
    validate_coordination_registry()
    for label, field, kind, owner, delete_owned in COORDINATION_FIELDS:
        model = apps.get_model(label)
        fields = ["pk", field]
        if owner:
            fields.append(owner)
        if kind == "bucket_kind":
            fields.append(kind)
        for row in model._base_manager.values(*fields).iterator(chunk_size=500):
            key = row[field]
            if not key:
                continue
            yield CoordinationReference(
                row[kind] if kind == "bucket_kind" else kind,
                str(key), row[owner] if owner else None,
                f"{label}:{row['pk']}:{field}", delete_owned,
            )
