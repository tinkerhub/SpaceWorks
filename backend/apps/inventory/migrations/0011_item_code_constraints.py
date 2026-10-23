"""Uniqueness for item codes, after 0010 has backfilled and committed the data."""

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0010_item_codes"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(
                condition=~Q(code=""),
                fields=("makerspace", "code"),
                name="uniq_category_code_per_makerspace",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventoryproduct",
            constraint=models.UniqueConstraint(
                condition=~Q(code_letter=""),
                fields=("makerspace", "category", "code_letter"),
                name="uniq_product_code_letter_per_category",
            ),
        ),
    ]
