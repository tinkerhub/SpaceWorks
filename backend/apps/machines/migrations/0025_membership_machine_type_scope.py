import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("machines", "0024_machine_type_makerspace_overrides"),
        ("makerspaces", "0073_makerspace_item_code_prefix_unique"),
    ]

    operations = [
        migrations.CreateModel(
            name="MembershipMachineTypeScope",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "machine_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="membership_scopes",
                        to="machines.machinetype",
                    ),
                ),
                (
                    "membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="machine_type_scopes",
                        to="makerspaces.makerspacemembership",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("membership", "machine_type"), name="membershipmachinetypescope_uniq"
                    )
                ],
            },
        ),
    ]
