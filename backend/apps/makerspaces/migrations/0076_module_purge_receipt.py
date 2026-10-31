import uuid

from django.db import migrations, models


FORWARD = """
CREATE FUNCTION module_purge_receipt_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'Module purge authority must be retained' USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.source_makerspace_id IS DISTINCT FROM OLD.source_makerspace_id
        OR NEW.source_public_code IS DISTINCT FROM OLD.source_public_code
        OR NEW.source_created_at IS DISTINCT FROM OLD.source_created_at
        OR NEW.module_key IS DISTINCT FROM OLD.module_key
        OR NEW.auth_generation IS DISTINCT FROM OLD.auth_generation
        OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
        OR NEW.storage_origins IS DISTINCT FROM OLD.storage_origins
        OR NEW.exact_keys IS DISTINCT FROM OLD.exact_keys
        OR NEW.namespace_clauses IS DISTINCT FROM OLD.namespace_clauses
        OR NEW.holder_sites IS DISTINCT FROM OLD.holder_sites
        OR NEW.charge_obligations IS DISTINCT FROM OLD.charge_obligations
        OR NEW.rollback_bindings IS DISTINCT FROM OLD.rollback_bindings
        OR NEW.graph_digest IS DISTINCT FROM OLD.graph_digest
        OR NEW.intent_created_at IS DISTINCT FROM OLD.intent_created_at THEN
        RAISE EXCEPTION 'Module purge authority is immutable' USING ERRCODE = '23514';
    END IF;
    IF (OLD.graph_purged_at IS NOT NULL AND NEW.graph_purged_at IS DISTINCT FROM OLD.graph_purged_at)
       OR (OLD.invalidated_at IS NOT NULL AND
           (NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at OR
            NEW.invalidation_reason IS DISTINCT FROM OLD.invalidation_reason))
       OR (OLD.last_attempt_at IS NOT NULL AND
           (NEW.last_attempt_at IS NULL OR NEW.last_attempt_at < OLD.last_attempt_at))
       OR (OLD.last_verified_at IS NOT NULL AND
           (NEW.last_verified_at IS NULL OR NEW.last_verified_at < OLD.last_verified_at)) THEN
        RAISE EXCEPTION 'Module purge checkpoint/invalidation is irreversible' USING ERRCODE = '23514';
    END IF;
    IF NEW.last_error_code NOT IN ('', 'cleanup_unconfirmed')
       OR NEW.invalidation_reason NOT IN ('', 'module_enabled', 'recovery', 'tenant_purged')
       OR ((NEW.invalidated_at IS NULL) <> (NEW.invalidation_reason = ''))
       OR NEW.graph_purged_at < NEW.intent_created_at
       OR NEW.invalidated_at < NEW.intent_created_at
       OR NEW.last_attempt_at < NEW.intent_created_at
       OR NEW.last_verified_at < NEW.intent_created_at
       OR (NEW.last_verified_at IS NOT NULL AND
           (NEW.graph_purged_at IS NULL OR NEW.last_attempt_at IS NULL OR
            NEW.last_verified_at < NEW.graph_purged_at OR NEW.last_verified_at > NEW.last_attempt_at)) THEN
        RAISE EXCEPTION 'Invalid module purge checkpoint' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER module_purge_receipt_guard BEFORE UPDATE OR DELETE ON makerspaces_modulepurgereceipt
FOR EACH ROW EXECUTE FUNCTION module_purge_receipt_guard();
ALTER TABLE makerspaces_modulepurgereceipt ENABLE ALWAYS TRIGGER module_purge_receipt_guard;

CREATE FUNCTION module_purge_enable_guard() RETURNS trigger AS $$
DECLARE
    added jsonb;
BEGIN
    SELECT coalesce(jsonb_agg(k), '[]'::jsonb) INTO added
      FROM jsonb_array_elements_text(NEW.enabled_modules) k
      WHERE NOT (coalesce(OLD.enabled_modules, '[]'::jsonb) ? k);
    IF EXISTS (SELECT 1 FROM makerspaces_modulepurgereceipt r
        WHERE r.source_makerspace_id = NEW.id AND r.invalidated_at IS NULL
          AND added ? r.module_key AND r.graph_purged_at IS NULL) THEN
        RAISE EXCEPTION 'Finish the module purge intent before enabling this module' USING ERRCODE = '23514';
    END IF;
    UPDATE makerspaces_modulepurgereceipt SET invalidated_at = statement_timestamp(),
        invalidation_reason = 'module_enabled'
      WHERE source_makerspace_id = NEW.id AND invalidated_at IS NULL
        AND added ? module_key AND graph_purged_at IS NOT NULL;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER module_purge_enable_guard BEFORE UPDATE OF enabled_modules ON makerspaces_makerspace
FOR EACH ROW EXECUTE FUNCTION module_purge_enable_guard();
ALTER TABLE makerspaces_makerspace ENABLE ALWAYS TRIGGER module_purge_enable_guard;
"""
REVERSE = """
DROP TRIGGER module_purge_enable_guard ON makerspaces_makerspace;
DROP FUNCTION module_purge_enable_guard();
DROP TRIGGER module_purge_receipt_guard ON makerspaces_modulepurgereceipt;
DROP FUNCTION module_purge_receipt_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0075_purge_receipt")]
    operations = [
        migrations.CreateModel(
            name="ModulePurgeReceipt",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("source_makerspace_id", models.PositiveBigIntegerField(editable=False)),
                ("source_public_code", models.CharField(max_length=32, editable=False)),
                ("source_created_at", models.DateTimeField(editable=False)),
                ("module_key", models.CharField(max_length=40, editable=False)),
                ("auth_generation", models.UUIDField(editable=False)),
                ("schema_version", models.PositiveSmallIntegerField(default=1, editable=False)),
                ("storage_origins", models.JSONField(editable=False)),
                ("exact_keys", models.JSONField(editable=False)),
                ("namespace_clauses", models.JSONField(editable=False)),
                ("holder_sites", models.JSONField(editable=False)),
                ("charge_obligations", models.JSONField(editable=False)),
                ("rollback_bindings", models.JSONField(editable=False)),
                ("graph_digest", models.CharField(max_length=64, editable=False)),
                ("intent_created_at", models.DateTimeField(editable=False)),
                ("graph_purged_at", models.DateTimeField(null=True, blank=True, editable=False)),
                ("invalidated_at", models.DateTimeField(null=True, blank=True, editable=False)),
                ("invalidation_reason", models.CharField(max_length=40, blank=True, editable=False)),
                ("last_attempt_at", models.DateTimeField(null=True, blank=True, editable=False)),
                ("last_verified_at", models.DateTimeField(null=True, blank=True, editable=False)),
                ("last_error_code", models.CharField(max_length=40, blank=True, editable=False)),
            ],
            options={
                "ordering": ("-intent_created_at",),
                "constraints": [models.UniqueConstraint(
                    fields=("source_makerspace_id", "module_key"),
                    condition=models.Q(invalidated_at__isnull=True),
                    name="module_purge_active_authority_unique",
                )],
            },
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
