"""Strip the retired in-app updater's module key from every makerspace.

The `updates` app keeps only its model for one release (see apps/updates/models.py), so this
migration touches no table: rollback and compound backups both depend on that table.
"""

from django.db import migrations


def remove_update_module_key(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    rows = Makerspace.objects.using(schema_editor.connection.alias)
    for space in rows.only("pk", "enabled_modules").iterator():
        modules = [key for key in (space.enabled_modules or []) if key != "updates"]
        if modules != space.enabled_modules:
            rows.filter(pk=space.pk).update(enabled_modules=modules)


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0069_checked_in_requires_space_id"),
    ]
    # Re-adding the key on reverse is not needed: an unknown key is tolerated and the
    # previous image re-derives its defaults.
    operations = [migrations.RunPython(remove_update_module_key, migrations.RunPython.noop)]
