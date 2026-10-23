"""The platform-wide component categories every makerspace starts with.

Each code is the middle part of an item code (TC-MCU-A). The full reference, with what
goes in each category and the classification rules, is docs/item-codes.md; the staff
console shows the same guide. Keep this list, migration 0010's copy of it and
``frontend/src/features/staff/panels/categoryStandard.ts`` in step.
"""

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


def ensure_default_categories(makerspace):
    """Create any standard category this makerspace does not have yet. Idempotent."""
    from django.utils.text import slugify

    from apps.inventory.models import Category

    existing = list(Category.objects.filter(makerspace=makerspace))
    codes = {category.code for category in existing}
    by_slug = {category.slug: category for category in existing}
    for order, (code, name) in enumerate(STANDARD_CATEGORIES):
        if code in codes:
            continue
        slug = slugify(name)
        match = by_slug.get(slug)
        if match is not None:
            if not match.code:
                match.code = code
                match.save(update_fields=["code", "updated_at"])
            continue
        Category.objects.create(
            makerspace=makerspace, name=name, slug=slug, code=code, display_order=order
        )
