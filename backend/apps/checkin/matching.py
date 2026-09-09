"""Normalising and matching a typed name against the upstream roster.

The roster carries no username, no email and no phone -- only a free-text display
name. Matching is therefore the whole of identity resolution here, and it is
deliberately the strictest thing that is still usable.

**Normalised-exact only. No fuzzy matching.** The roster is world-readable and
carries no secret, so a match is a presence claim rather than proof of identity
(see the posture note in `docs/INVARIANTS.md`). Fuzzy matching would widen the set
of people a given typed string can impersonate, which is the one property this
function must not have.
"""

import unicodedata


def normalize(name) -> str:
    """Casefold, NFKC-normalise, collapse internal whitespace, strip.

    Deliberately does NOT strip trailing punctuation. Real roster entries include
    ``"S AGNIVESH ."``, and dropping the period would silently merge it with a
    hypothetical ``"S AGNIVESH"`` -- two different people as far as we can tell.
    The cost is that such a person must type their name as it appears upstream.
    """
    text = unicodedata.normalize("NFKC", str(name or ""))
    # `split()` with no argument splits on arbitrary runs of any whitespace, which
    # is what collapses the double space in a real entry like "Don jo  Rois".
    return " ".join(text.split()).casefold()


def candidates(roster, typed_name):
    """Every roster entry whose normalised name equals the normalised input.

    Returns a list rather than a single entry: two checked-in people can genuinely
    share a display name, and the caller disambiguates them by avatar rather than
    guessing. An empty list means "no match", never "not eligible" -- eligibility
    is a separate question asked of an entry that already matched.
    """
    wanted = normalize(typed_name)
    if not wanted:
        return []
    return [entry for entry in roster if normalize(entry.name) == wanted]
