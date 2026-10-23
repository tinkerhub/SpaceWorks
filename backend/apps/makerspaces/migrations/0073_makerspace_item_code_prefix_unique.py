"""Item-code prefixes are unique across the platform (filled in by 0072)."""

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("makerspaces", "0072_makerspace_item_code_prefix"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="makerspace",
            constraint=models.UniqueConstraint(
                condition=~Q(item_code_prefix=""),
                fields=("item_code_prefix",),
                name="uniq_makerspace_item_code_prefix",
            ),
        ),
    ]
