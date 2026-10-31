from django.db import migrations, models


FORWARD = """
CREATE FUNCTION makerspace_purge_intent_monotonic() RETURNS trigger AS $$
BEGIN
    IF OLD.purge_started_at IS NOT NULL
       AND NEW.purge_started_at IS DISTINCT FROM OLD.purge_started_at THEN
        RAISE EXCEPTION 'Purge intent is irreversible; restore a pre-purge backup to recover data.'
            USING ERRCODE = '23514', CONSTRAINT = 'makerspace_purge_intent_monotonic';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER makerspace_purge_intent_monotonic
BEFORE UPDATE ON makerspaces_makerspace
FOR EACH ROW EXECUTE FUNCTION makerspace_purge_intent_monotonic();
"""
REVERSE = """
DROP TRIGGER makerspace_purge_intent_monotonic ON makerspaces_makerspace;
DROP FUNCTION makerspace_purge_intent_monotonic();
"""


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0073_makerspace_item_code_prefix_unique")]
    operations = [
        migrations.AddField(
            model_name="makerspace", name="purge_started_at",
            field=models.DateTimeField(null=True, blank=True, editable=False),
        ),
        migrations.AddConstraint(
            model_name="makerspace",
            constraint=models.CheckConstraint(
                condition=models.Q(purge_started_at__isnull=True)
                | models.Q(archived_at__isnull=False),
                name="makerspace_purge_requires_archive",
            ),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
