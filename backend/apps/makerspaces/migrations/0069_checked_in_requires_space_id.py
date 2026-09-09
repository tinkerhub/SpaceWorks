"""Both public-request-mode constraints, alone.

Separated from 0068 deliberately: an `AddConstraint` in the same atomic migration as a
`RunPython` row update on the same table can abort with "cannot ALTER TABLE because it
has pending trigger events" on any deployment that already has makerspaces. 0068 does
the data; this does the schema.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("makerspaces", "0068_public_request_mode"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="makerspace",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    public_request_mode__in=["disabled", "checked_in", "anyone"]
                ),
                name="makerspace_public_request_mode_known",
            ),
        ),
        migrations.AddConstraint(
            model_name="makerspace",
            constraint=models.CheckConstraint(
                condition=~models.Q(public_request_mode="checked_in")
                | models.Q(checkin_space_id__isnull=False),
                name="makerspace_checked_in_requires_space_id",
            ),
        ),
    ]
