"""Whether a matched roster entry may act, and why not when it may not.

Kept apart from `matching` because the two answer different questions and fail
differently: matching decides *who this is*, eligibility decides *whether they pass
the gate right now*. A caller that conflated them would be unable to tell "no such
person" from "that person has not chosen a project", and those produce different
messages -- one is a dead end, the other is fixable by the requester in the
TinkerHub app.
"""

from django.conf import settings

from apps.checkin.matching import normalize

# Reasons an otherwise-matched entry is refused. `ELIGIBLE` is the empty string so
# the whole set is falsy-when-fine and serialises straight to the API.
ELIGIBLE = ""
REASON_PURPOSE = "purpose"
REASON_PROJECT = "project"
REASON_EXPIRED = "expired"
REASON_SPACE = "space"


def required_purpose() -> str:
    """The upstream `purpose` string that admits a requester.

    A setting rather than a constant because the gate is exactly one upstream
    rename away from refusing everyone, and an operator must be able to correct
    that without waiting for a deploy.
    """
    return getattr(settings, "CHECKIN_REQUIRED_PURPOSE", "")


def refusal_reason(entry, now, *, space_id=None):
    """`ELIGIBLE`, or the first reason this entry is refused.

    Order matters for the message the requester sees: a wrong purpose is reported
    before a missing project, because choosing "Working on a project" upstream is
    what makes the project field appear in the first place. Telling someone to fill
    in a project they have no field for would be a dead end.
    """
    if space_id is not None and entry.space_id != space_id:
        return REASON_SPACE
    if normalize(entry.purpose) != normalize(required_purpose()):
        return REASON_PURPOSE
    if not entry.project_name.strip():
        return REASON_PROJECT
    # Belt and braces against a stale cached roster: the upstream endpoint is
    # already named `/active`, but a cached copy can outlive a checkout, and the
    # submit path must never admit someone who has left.
    if entry.check_out_time is not None and now >= entry.check_out_time:
        return REASON_EXPIRED
    return ELIGIBLE


def is_eligible(entry, now, *, space_id=None) -> bool:
    return refusal_reason(entry, now, space_id=space_id) == ELIGIBLE
