"""Item-code prefix per makerspace (TC in TC-MCU-A), unique across the platform.

Existing makerspaces get the same default a new one would ("Tinkerspace Kochi" → TK),
assigned oldest first so the first makerspace keeps the plain initials on a collision.
The derivation is copied here rather than imported so later edits to
`apps.makerspaces.item_code_prefix` cannot change what this migration did. The unique
constraint is added in 0073, after this data migration has committed.
"""

import re
import string

import django.core.validators
from django.db import migrations, models

_ALNUM = string.ascii_uppercase + string.digits


def _candidates(name):
    words = re.findall(r"[A-Z0-9]+", (name or "").upper()) or ["SW"]
    first = words[0][0]
    last = words[-1] if len(words) > 1 else words[0][1:]
    middle = "".join(words[1:-1]) + (words[0][1:] if len(words) > 1 else "")
    seen = set()
    for second in [*last, *middle, *_ALNUM]:
        if second not in seen:
            seen.add(second)
            yield first + second
    for second in _ALNUM:
        for third in _ALNUM:
            yield first + second + third


def assign_prefixes(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    taken = set()
    for makerspace in Makerspace.objects.order_by("id"):
        prefix = next(c for c in _candidates(makerspace.name) if c not in taken)
        taken.add(prefix)
        Makerspace.objects.filter(pk=makerspace.pk).update(item_code_prefix=prefix)


class Migration(migrations.Migration):

    dependencies = [
        ("makerspaces", "0071_makerspace_checkin_api_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="makerspace",
            name="item_code_prefix",
            field=models.CharField(
                blank=True,
                default="",
                max_length=6,
                validators=[
                    django.core.validators.RegexValidator(
                        "^[A-Z0-9]{1,6}$", "Use 1–6 capital letters or digits, e.g. TC."
                    )
                ],
            ),
        ),
        migrations.RunPython(assign_prefixes, migrations.RunPython.noop),
    ]
