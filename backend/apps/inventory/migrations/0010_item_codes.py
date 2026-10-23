"""Category codes and item letters for the platform-wide item code (TC-MCU-A).

For every existing makerspace this:

1. gives the old default categories their matching code (Microcontrollers → MCU,
   Sensors → SNS, Actuators → ACT, Cables → CBL, Accessories → MOD) — names, slugs and
   rows are untouched, so notification category scopes keep pointing at them;
2. gives a category already named like a standard one (e.g. "Displays") that code, and
   adds whichever standard categories are still missing; SBCs and Microprocessors are
   left without a code for staff to merge;
3. gives every categorised product a letter in creation order and records how many
   letters each category has issued.

Nothing is deleted or renamed. The unique constraints are added in 0011: Postgres refuses to
build an index on a table with pending trigger events from the inserts above in the same
transaction. The standard list is copied here, not imported, so later
edits to `apps.inventory.categories` cannot change what this migration did.
"""

import django.core.validators
from django.db import migrations, models
from django.utils.text import slugify

STANDARD_CATEGORIES = (
    ("MCU", "Microcontrollers & Computing Boards"),
    ("SNS", "Sensors"),
    ("ACT", "Actuators"),
    ("PWR", "Power & Power Management"),
    ("NET", "Networking & Communication"),
    ("MOD", "Modules & Accessories"),
    ("CBL", "Cables & Connectors"),
    ("CON", "Consumables"),
    ("DSP", "Displays"),
    ("DRV", "Motor Drivers & Motion Control"),
)
LEGACY_SLUG_CODES = {
    "microcontrollers": "MCU",
    "sensors": "SNS",
    "actuators": "ACT",
    "cables": "CBL",
    "accessories": "MOD",
}


def _letter(index):
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def assign_codes(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    Category = apps.get_model("inventory", "Category")
    InventoryProduct = apps.get_model("inventory", "InventoryProduct")
    for makerspace in Makerspace.objects.order_by("id"):
        categories = list(Category.objects.filter(makerspace=makerspace))
        used = set()
        for category in categories:
            code = LEGACY_SLUG_CODES.get(category.slug)
            if code and code not in used:
                used.add(code)
                Category.objects.filter(pk=category.pk).update(code=code)
        by_slug = {category.slug: category for category in categories}
        for order, (code, name) in enumerate(STANDARD_CATEGORIES):
            if code in used:
                continue
            match = by_slug.get(slugify(name))
            if match is not None:
                if match.slug not in LEGACY_SLUG_CODES:
                    Category.objects.filter(pk=match.pk).update(code=code)
                continue
            Category.objects.create(
                makerspace=makerspace,
                name=name,
                slug=slugify(name),
                code=code,
                display_order=order,
            )
    for category in Category.objects.order_by("id"):
        product_ids = InventoryProduct.objects.filter(category=category).order_by(
            "id"
        ).values_list("id", flat=True)
        count = 0
        for count, product_id in enumerate(product_ids, start=1):
            InventoryProduct.objects.filter(pk=product_id).update(
                code_letter=_letter(count - 1)
            )
        Category.objects.filter(pk=category.pk).update(code_sequence=count)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0009_inventoryproduct_image_key"),
        ("makerspaces", "0073_makerspace_item_code_prefix_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="code",
            field=models.CharField(
                blank=True,
                default="",
                max_length=4,
                validators=[
                    django.core.validators.RegexValidator(
                        "^[A-Z]{2,4}$", "Use 2–4 capital letters, e.g. MCU."
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="category",
            name="code_sequence",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name="inventoryproduct",
            name="code_letter",
            field=models.CharField(blank=True, default="", editable=False, max_length=4),
        ),
        migrations.RunPython(assign_codes, migrations.RunPython.noop),
    ]
