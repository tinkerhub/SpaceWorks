"""Replace the account-less boolean with a single public-request mode.

AddField -> RunPython -> RemoveField rather than RenameField: PostgreSQL cannot
reinterpret a boolean column as the new string enum, and a rename would leave the
old values unconvertible in the same statement.

The data step is the whole point of the migration and is deliberately explicit:
``True`` becomes ``anyone`` (the only open state the boolean could express) and
everything else becomes ``disabled``. No row can become ``checked_in`` here, because
that mode also needs an upstream space binding that no existing row has.
"""

from django.db import migrations, models


def boolean_to_mode(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    Makerspace.objects.filter(anonymous_requests_enabled=True).update(
        public_request_mode="anyone"
    )
    Makerspace.objects.filter(anonymous_requests_enabled=False).update(
        public_request_mode="disabled"
    )


def mode_to_boolean(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    Makerspace.objects.update(anonymous_requests_enabled=False)
    Makerspace.objects.filter(public_request_mode="anyone").update(
        anonymous_requests_enabled=True
    )
    # `checked_in` reverses to False, not True: the boolean has no way to express the
    # check-in gate, and reversing it to "anyone" would silently OPEN a space that had
    # been gated. Losing the gate on a downgrade is the safe direction.


def close_unbound_checked_in_modes(apps, schema_editor):
    """Existing rows migrate in the same fail-closed direction as the runtime policy.

    Runs here rather than beside the constraint: PostgreSQL aborts an ALTER TABLE that
    follows a row update on the same table inside one transaction ("pending trigger
    events"), and this table carries the scoped-PII triggers that make that fire.
    """
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    Makerspace.objects.filter(
        public_request_mode="checked_in", checkin_space_id__isnull=True
    ).update(public_request_mode="disabled")


class Migration(migrations.Migration):

    dependencies = [
        ("makerspaces", "0067_reconcile_anonymous_requests_with_membership"),
    ]

    operations = [
        migrations.AddField(
            model_name="makerspace",
            name="public_request_mode",
            field=models.CharField(
                choices=[
                    ("disabled", "An account is required"),
                    ("checked_in", "Anyone checked in upstream and working on a project"),
                    ("anyone", "Anyone, no account needed"),
                ],
                default="disabled",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="makerspace",
            name="checkin_space_id",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.RunPython(boolean_to_mode, mode_to_boolean),
        migrations.RemoveField(
            model_name="makerspace",
            name="anonymous_requests_enabled",
        ),
        migrations.RunPython(
            close_unbound_checked_in_modes, migrations.RunPython.noop
        ),
    ]
