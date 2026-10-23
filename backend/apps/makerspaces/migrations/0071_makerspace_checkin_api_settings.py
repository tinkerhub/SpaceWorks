"""Per-makerspace check-in roster settings.

All three columns default to blank, which `apps.checkin.config.checkin_config` reads as
"use the deployment setting", so every existing makerspace keeps exactly the roster,
purpose and provider name it used before this migration.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("makerspaces", "0070_remove_in_app_updates"),
    ]

    operations = [
        migrations.AddField(
            model_name="makerspace",
            name="checkin_api_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="makerspace",
            name="checkin_required_purpose",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="makerspace",
            name="checkin_provider_name",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
