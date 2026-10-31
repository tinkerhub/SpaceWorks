import uuid

from django.db import migrations, models


FORWARD = """
CREATE FUNCTION purge_receipt_immutable_authority() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        -- Scratch archive projection already owns this transaction-local delete
        -- authority. It must omit receipts instead of packaging runnable state.
        IF current_setting('app.allow_immutable_delete', true) = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Purge receipt locators must be retained indefinitely' USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.source_makerspace_id IS DISTINCT FROM OLD.source_makerspace_id
        OR NEW.source_purge_started_at IS DISTINCT FROM OLD.source_purge_started_at
        OR NEW.auth_generation IS DISTINCT FROM OLD.auth_generation
        OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
        OR NEW.storage_origins IS DISTINCT FROM OLD.storage_origins
        OR NEW.exact_keys IS DISTINCT FROM OLD.exact_keys
        OR NEW.namespace_prefixes IS DISTINCT FROM OLD.namespace_prefixes
        OR NEW.graph_purged_at IS DISTINCT FROM OLD.graph_purged_at THEN
        RAISE EXCEPTION 'Purge receipt authority is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.invalidated_at IS NOT NULL AND NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at THEN
        RAISE EXCEPTION 'Purge receipt invalidation is irreversible' USING ERRCODE = '23514';
    END IF;
    IF NEW.last_error_code NOT IN ('', 'cleanup_unconfirmed') THEN
        RAISE EXCEPTION 'Unsupported purge receipt outcome code' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER purge_receipt_immutable_authority
BEFORE UPDATE OR DELETE ON makerspaces_purgereceipt
FOR EACH ROW EXECUTE FUNCTION purge_receipt_immutable_authority();
"""
REVERSE = """
DROP TRIGGER purge_receipt_immutable_authority ON makerspaces_purgereceipt;
DROP FUNCTION purge_receipt_immutable_authority();
"""


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0074_makerspace_purge_started_at")]
    operations = [
        migrations.CreateModel(
            name="PurgeReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_makerspace_id", models.PositiveBigIntegerField(editable=False)),
                ("source_purge_started_at", models.DateTimeField(editable=False)),
                ("auth_generation", models.UUIDField(editable=False)),
                ("schema_version", models.PositiveSmallIntegerField(default=1, editable=False)),
                ("storage_origins", models.JSONField(editable=False)),
                ("exact_keys", models.JSONField(editable=False)),
                ("namespace_prefixes", models.JSONField(editable=False)),
                ("graph_purged_at", models.DateTimeField(editable=False)),
                ("invalidated_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("last_verified_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("last_error_code", models.CharField(blank=True, editable=False, max_length=40)),
            ],
            options={"ordering": ("-graph_purged_at",)},
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
