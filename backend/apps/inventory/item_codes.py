"""Platform-wide item codes: ``<makerspace prefix>-<category code>-<letter>``, e.g. TC-MCU-A.

Only the parts are stored — ``Makerspace.item_code_prefix``, ``Category.code`` and
``InventoryProduct.code_letter`` — and the full code is assembled on read. Renaming a
prefix or a category code therefore re-labels every item at once instead of leaving
stale copies behind.

Letters are issued from ``Category.code_sequence`` under a row lock and never reused:
deleting TC-MCU-B does not free "B", so an old printed label can never come to name a
different part (renaming the prefix or a category code is the one exception: it frees the old
value, and docs/item-codes.md tells operators to reprint). Every categorised product holds a letter, even in a category with no
code yet, so giving a category a code later needs no backfill.
"""

import re

from django.db import transaction
from django.db.models import DEFERRED, Q

CATEGORY_CODE_RE = re.compile(r"^[A-Z]{2,4}$")
PREFIX_RE = re.compile(r"^[A-Z0-9]{1,6}$")
# The prefix is optional when searching: "MCU-A" finds TC-MCU-A in this makerspace.
ITEM_CODE_RE = re.compile(r"^(?:([A-Z0-9]{1,6})-)?([A-Z]{2,4})-([A-Z]{1,4})$")


def letter_for_index(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA, 27 → AB (spreadsheet columns)."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def format_item_code(prefix, category_code, letter) -> str:
    if not (category_code and letter):
        return ""
    return f"{prefix}-{category_code}-{letter}" if prefix else f"{category_code}-{letter}"


def item_code(product) -> str:
    category = product.category if product.category_id else None
    if category is None:
        return ""
    return format_item_code(
        product.makerspace.item_code_prefix, category.code, product.code_letter
    )


def issue_letter(category_id) -> str:
    """The next unused letter in this category. Locks the category row."""
    from apps.inventory.models import Category, InventoryProduct

    with transaction.atomic():
        # NO KEY: products referencing this category keep inserting while it is held.
        category = Category.objects.select_for_update(no_key=True).get(pk=category_id)
        used = set(
            InventoryProduct.objects.filter(category_id=category_id)
            .exclude(code_letter="")
            .values_list("code_letter", flat=True)
        )
        letter = letter_for_index(category.code_sequence)
        # Belt and braces: a counter restored from an old backup must not reissue a letter.
        while letter in used:
            category.code_sequence += 1
            letter = letter_for_index(category.code_sequence)
        category.code_sequence += 1
        category.save(update_fields=["code_sequence"])
    return letter


def sync_code_letter(product, update_fields=None) -> bool:
    """Give the product a letter in its current category. Returns True if it changed.

    Called from ``InventoryProduct.save()`` so every writer — the staff API, bulk
    import, procurement, seed_demo, the Django admin — gets the same behaviour.
    """
    if update_fields is not None and not {"category", "category_id"} & set(update_fields):
        return False  # a partial save that does not write the category keeps its letter
    if product.category_id is None:
        if product.code_letter:
            product.code_letter = ""
            return True
        return False
    if product.code_letter:
        if product._state.adding:
            return False  # an imported or restored row arrives with its own letter
        if product.category_id == _loaded_category_id(product):
            return False
    product.code_letter = issue_letter(product.category_id)
    return True


def _loaded_category_id(product):
    loaded = getattr(product, "_loaded_category_id", DEFERRED)
    if loaded is DEFERRED:
        loaded = (
            type(product)._base_manager.filter(pk=product.pk)
            .values_list("category_id", flat=True)
            .first()
        )
    return loaded


def item_code_q(text):
    """A filter matching products whose item code is ``text``; matches nothing otherwise.

    Callers OR it with their text search, so "USB-C" still finds products named USB-C.
    """
    match = ITEM_CODE_RE.match(text.strip().upper())
    if not match:
        return Q(pk__in=[])
    prefix, category_code, letter = match.groups()
    q = Q(category__code=category_code, code_letter=letter)
    if prefix:
        q &= Q(makerspace__item_code_prefix=prefix)
    return q
