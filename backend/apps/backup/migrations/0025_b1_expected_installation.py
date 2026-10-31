"""Bind pre-cutover progress to exact manifest-compiled installation facts."""

from importlib import import_module

from django.db import migrations, models


def _frozen(name, constant="SQL"):
    return getattr(import_module(f"apps.backup.migrations._0025_{name}_sql"), constant)


FORWARD = "\n".join(_frozen(name) for name in (
    "expectation", "source_shape", "sequence", "installation", "trigger", "stage",
))
REVERSE = "\n".join((
    _frozen("stage", "REVERSE"),
    _frozen("trigger", "REVERSE"),
    "DROP FUNCTION public.backup_b1_prove_installation(public.backup_b1restoreoperationstate, boolean, boolean);",
    "DROP FUNCTION public.backup_b1_expected_inventory(public.backup_b1restoreoperationstate);",
    "DROP FUNCTION public.backup_b1_prove_sequences(jsonb);",
    "DROP FUNCTION public.backup_b1_sequence_shape(jsonb);",
    "DROP FUNCTION public.backup_b1_source_shape(jsonb, text[]);",
    "DROP FUNCTION public.backup_b1_string_array(jsonb);",
    "DROP FUNCTION public.backup_b1_live_guard(oid, oid);",
    "DROP FUNCTION public.backup_b1_exact_keys(jsonb, text[]);",
    "DROP FUNCTION public.backup_b1_canonical_json(jsonb);",
))


class Migration(migrations.Migration):
    dependencies = [("backup", "0024_archive_promotion_fencing")]
    operations = [
        migrations.AddField(
            model_name="b1restoreoperationstate", name="expected_installation",
            field=models.TextField(blank=True, default="", editable=False),
        ),
        migrations.AddField(
            model_name="b1restoreoperationstate", name="expected_installation_sha256",
            field=models.CharField(max_length=64, blank=True, default="", editable=False),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
