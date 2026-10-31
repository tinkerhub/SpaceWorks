"""Keep fence continuity OIDs numeric in the exact installation proof."""

from django.db import migrations

from ._0026_installation_sql import REVERSE, SQL


class Migration(migrations.Migration):
    dependencies = [("backup", "0025_b1_expected_installation")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
