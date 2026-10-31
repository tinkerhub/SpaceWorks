"""Register the machine-service feature on existing notification choice fields."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0024_machinetypeemailtemplate"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationpreference",
            name="feature",
            field=models.CharField(choices=[
                ("hardware_requests", "Hardware requests"), ("printing", "Printing"),
                ("machine_service", "Machine services"), ("events", "Events"),
                ("bookings", "Bookings"), ("maintenance", "Maintenance"), ("members", "Members"),
            ], max_length=32),
        ),
        migrations.AlterField(
            model_name="notificationdeliverylog",
            name="feature",
            field=models.CharField(choices=[
                ("hardware_requests", "Hardware requests"), ("printing", "Printing"),
                ("machine_service", "Machine services"), ("events", "Events"),
                ("bookings", "Bookings"), ("maintenance", "Maintenance"), ("members", "Members"),
            ], max_length=32),
        ),
        migrations.AlterField(
            model_name="notificationrecipient",
            name="feature",
            field=models.CharField(choices=[
                ("hardware_requests", "Hardware requests"), ("printing", "Printing"),
                ("machine_service", "Machine services"), ("events", "Events"),
                ("bookings", "Bookings"), ("maintenance", "Maintenance"), ("members", "Members"),
            ], max_length=32),
        ),
        migrations.AlterField(
            model_name="chattemplate",
            name="feature",
            field=models.CharField(choices=[
                ("hardware_requests", "Hardware requests"), ("printing", "Printing"),
                ("machine_service", "Machine services"), ("events", "Events"),
                ("bookings", "Bookings"), ("maintenance", "Maintenance"), ("members", "Members"),
            ], max_length=32),
        ),
    ]
