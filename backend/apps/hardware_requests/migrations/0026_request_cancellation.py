"""Accepted requests may be cancelled before any handover."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hardware_requests", "0025_checkin_provenance")]

    operations = [
        migrations.AddField(
            model_name="hardwarerequest",
            name="cancellation_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="hardwarerequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("pending_approval", "Pending Approval"),
                    ("rejected", "Rejected"),
                    ("accepted", "Accepted"),
                    ("cancelled", "Cancelled"),
                    ("issued", "Issued"),
                    ("partially_returned", "Partially Returned"),
                    ("returned", "Returned"),
                    ("closed_with_issue", "Closed with Issue"),
                ],
                db_index=True,
                default="pending_approval",
                max_length=32,
            ),
        ),
    ]
