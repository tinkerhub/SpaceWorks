"""The short makerspace prefix that starts every item code (TC in TC-MCU-A).

Prefixes are unique across the platform so a code names one part on one makerspace
anywhere it is read. The default is the first letter of the first word plus the first
letter of the last ("Tinkerspace Calicut" → TC, "Tinkerspace Kochi" → TK). When that is
taken, the first letter stays and the second letter moves on through the rest of the
name ("Tinkerspace Chennai" → TH), then A–Z and 0–9, and only then grows to three
characters. An operator can override it in settings; ``validate_prefix`` refuses a
prefix another makerspace already holds.
"""

import re
import string

from apps.inventory.item_codes import PREFIX_RE

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


def derive_prefix(name, taken) -> str:
    taken = {value.upper() for value in taken}
    for candidate in _candidates(name):
        if candidate not in taken:
            return candidate
    raise RuntimeError("No free item-code prefix is left for this makerspace name.")


def taken_prefixes(exclude_pk=None):
    from apps.makerspaces.models import Makerspace

    return set(
        Makerspace.objects.exclude(pk=exclude_pk)
        .exclude(item_code_prefix="")
        .values_list("item_code_prefix", flat=True)
    )


def validate_prefix(value, *, exclude_pk=None) -> str:
    """Normalised prefix, or ValueError with a message fit for the operator."""
    value = (value or "").strip().upper()
    if not PREFIX_RE.match(value):
        raise ValueError("Use 1–6 letters or digits, e.g. TC.")
    if value in taken_prefixes(exclude_pk):
        raise ValueError(f"{value} is already used by another makerspace.")
    return value
