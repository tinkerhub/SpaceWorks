"""Whether a report, and which of its columns, applies to a makerspace's installed modules.

Off means absent (docs/INVARIANTS.md, "Off means absent, in catalogs and counters too"): a
report whose source modules are all switched off is left out of the catalog and refused,
rather than listed as "unavailable", and a section-based report drops the columns of a
switched-off section instead of printing them as "No".
"""

from rest_framework.exceptions import ValidationError

from apps.makerspaces.guards import require_module
from apps.makerspaces.platform import module_enabled


def report_applicable(definition, makerspace):
    """Every required module is on and, for a section report, at least one section is."""
    if not all(module_enabled(makerspace, key) for key in definition.required_modules):
        return False
    return not definition.section_modules or any(
        module_enabled(makerspace, key) for key in definition.section_modules
    )


def require_report_applicable(definition, makerspace):
    """The view-boundary form of `report_applicable`: the same 400 shape as `require_module`."""
    for key in definition.required_modules:
        require_module(makerspace, key)
    if definition.section_modules and not any(
        module_enabled(makerspace, key) for key in definition.section_modules
    ):
        raise ValidationError({"module": "Every module this report covers is disabled for this makerspace."})


def off_section_prefixes(definition, enabled):
    """Column prefixes (`events_`) of sections whose module `enabled(key)` says is off."""
    return tuple(f"{key}_" for key in definition.section_modules if not enabled(key))


def applicable_fields(definition, makerspace):
    """The catalog's field list with the columns of switched-off sections removed."""
    prefixes = off_section_prefixes(definition, lambda key: module_enabled(makerspace, key))
    return [field for field in definition.fields if not field.startswith(prefixes)] if prefixes else list(definition.fields)
