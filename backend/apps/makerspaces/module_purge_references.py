"""Only exact typed sites removed in the final transaction may reference bytes."""

from apps.backup.object_reference_capture import build_object_ownership_plan

from .purge_object_closure import STAGED_PRIVATE_MODELS, _aliases
from .purge_object_references import coordination_references
from .purge_storage import PurgeStorageRefused, bucket_name


def assert_unreferenced(closure, sites=()):
    physical = {(bucket_name(kind), key) for kind, key in closure}
    allowed = {(f"{label}:{pk}:{field}", bucket_name(kind), key)
               for label, pk, field, kind, key in sites}
    plan = build_object_ownership_plan([])
    refs = [(ref.site, ref.bucket_kind, ref.object_key,
             ref.site.split(":", 1)[0] in STAGED_PRIVATE_MODELS) for ref in plan.references]
    refs.extend((ref.site, ref.kind, ref.key, ref.site.startswith("tenant_migration.TenantImportObject:"))
                for ref in coordination_references())
    for site, kind, key, staged in refs:
        hits = any((bucket_name(k), alias) in physical for k, alias in _aliases(kind, key, staged=staged))
        if hits and (site, bucket_name(kind), key) not in allowed:
            raise PurgeStorageRefused("A retained, shared, global, audit or import object reference prevents module cleanup.")
