import django.core.validators
from django.db import migrations, models


# The platform default moved from usd to inr. Rows still on the old default are flipped
# with it; a row an operator set to any other currency is left alone. Payment rows carry
# their own currency and are untouched, so already-raised charges keep what they were.
def forwards(apps, schema_editor):
    apps.get_model("payments", "MakerspacePaymentSettings").objects.filter(
        default_currency="usd"
    ).update(default_currency="inr")


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0013_allow_waived_online_settlement"),
    ]

    operations = [
        migrations.AlterField(
            model_name="makerspacepaymentsettings",
            name="default_currency",
            field=models.CharField(
                default="inr",
                max_length=3,
                validators=[
                    django.core.validators.RegexValidator(
                        message="Default currency must be a three-letter lowercase ISO currency code.",
                        regex="^[a-z]{3}$",
                    )
                ],
            ),
        ),
        # No reverse flip: after this runs, an inr row may be one the operator chose before
        # the upgrade, and turning it back into usd would rewrite their setting.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
