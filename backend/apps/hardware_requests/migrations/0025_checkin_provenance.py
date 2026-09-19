"""Upstream check-in provenance on a borrow request.

Nullable/blank throughout: these are populated only by the `checked_in` request
policy, and every existing row predates it.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hardware_requests", "0024_anonymous_request_submission"),
        ("checkin", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="hardwarerequest",
            name="checkin_identity",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="hardware_requests",
                to="checkin.checkinidentity",
            ),
        ),
        migrations.AddField(
            model_name="hardwarerequest",
            name="checkin_project_name",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="hardwarerequest",
            name="checkin_purpose",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="hardwarerequest",
            name="checkin_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
