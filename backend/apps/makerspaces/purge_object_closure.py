"""Freeze typed tenant closure and reject foreign/global/shared byte references."""

from apps.backup.object_reference_capture import build_object_ownership_plan
from apps.makerspaces.purge_object_references import coordination_references
from apps.makerspaces.purge_storage import PurgeStorageRefused, bucket_name, list_versions
from apps.makerspaces.storage_key_collectors import (
    collect_private_object_keys, collect_public_image_keys,
)


# Exact numeric tenant framing, including retained legacy namespaces. Never use
# substring ownership: `items/1/` cannot address `items/11/`.
PUBLIC_ROOTS = (
    "items", "machine", "makerspace", "member", "event", "event-series",
    "printers", "spaces",
)
PRIVATE_ROOTS = (
    "evidence", "machines", "machine", "warranty", "procurement",
    "event-certificates", "data-exports", "tenant-migrations", "print",
)
STAGED_PRIVATE_MODELS = frozenset({
    "evidence.EvidencePhoto", "events.EventAttendanceCertificate",
    "machines.MachineDocument", "machines.ServiceRequestFile",
    "maintenance.MaintenanceLogDocument", "procurement.ToBuyReceipt", "warranty.WarrantyDocument",
})
STAGED_PRIVATE_ROOTS = frozenset({
    "evidence", "machines", "machine", "warranty", "procurement",
    "event-certificates", "print",
})


def tenant_prefixes(makerspace_id, kind):
    roots = PUBLIC_ROOTS if kind == "public_image" else PRIVATE_ROOTS
    final = tuple(f"{root}/{int(makerspace_id)}/" for root in roots)
    staged = tuple(f"staging/{prefix}" for prefix in final if (
        kind == "public_image" or prefix.split("/", 1)[0] in STAGED_PRIVATE_ROOTS
    ))
    return final + staged


def _safe_key(key):
    if (not isinstance(key, str) or not key or key.startswith("/")
            or any(part in {"", ".", ".."} for part in key.split("/"))
            or any(ord(char) < 32 for char in key) or "\\" in key):
        raise PurgeStorageRefused("An object reference has an unsafe or unknown key format.")
    return key


def _aliases(kind, key, *, staged=False):
    _safe_key(key)
    yield kind, key
    root = key.split("/", 1)[0]
    if not key.startswith("staging/") and (
        staged or kind == "public_image"
        or (kind == "private" and root in STAGED_PRIVATE_ROOTS)
    ):
        yield kind, f"staging/{key}"


def _owned_extra_keys(space):
    from apps.backup.models import RestoreRollbackObject
    from apps.admin_api.models import BulkImportJob
    from apps.tenant_migration.models import TenantImportJob

    extra = set()
    # These uploads have a dated, non-tenant namespace. Only exact typed row
    # locators qualify; there is no safe broad-prefix deletion authority.
    uploads = list(BulkImportJob.objects.filter(makerspace=space).exclude(upload="").values_list("upload", flat=True))
    if uploads:
        from django.conf import settings
        from storages.backends.s3 import S3Storage

        storage = BulkImportJob._meta.get_field("upload").storage
        if (not isinstance(storage, S3Storage) or storage.location
                or storage.bucket_name != settings.AWS_STORAGE_BUCKET_NAME
                or storage.endpoint_url != settings.AWS_S3_ENDPOINT_URL):
            raise PurgeStorageRefused("Bulk import upload storage origin cannot be proven.")
    for key in uploads:
        _safe_key(str(key))
        if not str(key).startswith("bulk-imports/"):
            raise PurgeStorageRefused("Bulk import upload has an unknown storage namespace.")
        extra.add(("private", str(key)))
    import_prefixes = []
    for job_id in TenantImportJob.objects.filter(target_makerspace=space).values_list("pk", flat=True):
        import_prefixes.append(f"tenant-imports/{job_id}/")
        for kind in ("private", "public_image"):
            extra.add((kind, f"migrated-objects/{job_id}/"))
            extra.add((kind, f"staging/migrated-objects/{job_id}/"))
    for kind, key, restore_id, source in RestoreRollbackObject.objects.filter(
        makerspace=space,
    ).values_list("bucket_kind", "copy_key", "restore_id", "source_key"):
        if key:
            if key != f"rollback/{restore_id}/{kind}/{source}":
                raise PurgeStorageRefused("Rollback copy ownership cannot be proven.")
            extra.add((kind, key))
    return extra, import_prefixes


def freeze_closure(space, s3, verify_boundary, *, extra_keys=()):
    target = int(space.pk)
    from apps.tenant_migration.models import TenantImportJob

    # Target import tasks intentionally bypass source quiescence and can reuse a
    # source namespace. Existing unfinished jobs are not frozen by our source locks.
    if TenantImportJob.objects.exclude(status__in=TenantImportJob.TERMINAL_STATUSES).exists():
        raise PurgeStorageRefused("An unfinished tenant import prevents exclusive object ownership proof.")
    # This validates the drift-guarded model/field registry, all retention states,
    # and audit meta variants across ALL tenants before any deletion is attempted.
    plan = build_object_ownership_plan([target])
    references = []
    candidates = set()
    for ref in plan.references:
        owner = ref.canonical_makerspace_id
        if owner is None:
            owner = ref.coordination_makerspace_id
        if ref.coordination_policy in {"recursive_archive_reference", "recursive_tenant_exit_artifact"}:
            # These retained archive rows survive with a SET_NULL tenant FK.
            # Their bytes are outside the purge graph and remain foreign references.
            owner = None
        staged = ref.site.split(":", 1)[0] in STAGED_PRIVATE_MODELS
        references.append((ref.bucket_kind, ref.object_key, owner, staged))
        if owner == target:
            candidates.update(_aliases(ref.bucket_kind, ref.object_key, staged=staged))
    for ref in coordination_references():
        staged = ref.site.startswith("tenant_migration.TenantImportObject:")
        references.append((ref.kind, ref.key, ref.owner, staged))
        if ref.owner == target and ref.delete_owned:
            candidates.update(_aliases(ref.kind, ref.key))
    for key in collect_private_object_keys(space):
        candidates.update(_aliases("private", key))
    for key in collect_public_image_keys(space):
        candidates.update(_aliases("public_image", key))

    extras, import_prefixes = _owned_extra_keys(space)
    # Only validated source-local module receipts may supply these exact keys.
    # prepare_receipt still rejects any incompatible whole-tenant grammar before bytes.
    extras.update(extra_keys)
    candidates.update(extra_keys)
    prefixes = {kind: list(tenant_prefixes(target, kind)) for kind in ("private", "public_image")}
    prefixes["private"].extend(import_prefixes)
    for kind, key in extras:
        if key.endswith("/"):
            prefixes[kind].append(key)
    for kind, values in prefixes.items():
        for prefix in values:
            verify_boundary()
            for row in list_versions(s3, bucket_name(kind), prefix):
                candidates.add((kind, _safe_key(row["Key"])))
    for kind, key in candidates:
        if (kind, key) not in extras and not any(key.startswith(prefix) for prefix in prefixes[kind]):
            raise PurgeStorageRefused(
                "An object key is outside the proven tenant namespaces; purge is unsupported for this graph."
            )

    # Compare actual physical bucket+key identities, so configuring both logical
    # bucket kinds to one bucket cannot hide a shared reference.
    physical = {(bucket_name(kind), key) for kind, key in candidates}
    for kind, key, owner, staged in references:
        for alias_kind, alias_key in _aliases(kind, key, staged=staged):
            if (bucket_name(alias_kind), alias_key) in physical and owner != target:
                raise PurgeStorageRefused("A purge object is referenced by a foreign or global row.")
    return frozenset(candidates), sorted({(kind, prefix) for kind, values in prefixes.items() for prefix in values})
