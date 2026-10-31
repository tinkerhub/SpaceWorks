"""Conservative cleanup checks, including global and imported raw references."""
from django.apps import apps
from django.core.exceptions import FieldError
from django.db import DatabaseError

from apps.backup.object_ownership_registry import FIELD_OBJECT_RULES
from apps.makerspaces.purge_object_references import COORDINATION_FIELDS


def key_in_use(kind, key):
    # Import reservations are global, including jobs whose target_makerspace is
    # still NULL or was cleared. This preflight cannot close the earlier window
    # before the journal insert; version-specific deletion supplies that safety.
    import_target = "tenant_migration.TenantImportObject"
    if _reference_exists(import_target, {"target_key": key, "bucket_kind": kind}):
        return True
    for rule in FIELD_OBJECT_RULES:
        filters = {rule.field_name: key}
        if rule.bucket == "from_row":
            filters["bucket_kind"] = kind
        elif rule.bucket != kind:
            continue
        if _reference_exists(rule.model_label, filters):
            return True
    for label, field, bucket, _owner, _delete_owned in COORDINATION_FIELDS:
        if (label, field) == (import_target, "target_key"):
            continue  # Already checked independently of the purge registry.
        filters = {field: key}
        if bucket == "bucket_kind":
            filters["bucket_kind"] = kind
        elif bucket != kind:
            continue
        if _reference_exists(label, filters):
            return True
    return False


def _reference_exists(label, filters):
    try:
        model = apps.get_model(label)
        # Tombstoned models still retain rows: never skip their queries based on
        # runtime activation. Removed models/tables cannot establish absence.
        return model is None or model._base_manager.filter(**filters).exists()
    except (LookupError, FieldError, DatabaseError):
        return True


def private_key_in_use(key):
    return key_in_use("private", key)
