"""Submit-time verification: the roster is the authorization fact, so it is refetched.

The lookup response is NEVER trusted as a token. A caller can send any `mid`, and a
mid that was eligible sixty seconds ago may have checked out since -- so the entry is
re-resolved against a FRESH roster, and the name is re-matched against it, before any
principal is minted or any request is written.

Refusals are split deliberately, because they mean different things to the person
standing at the desk:

* ``not_checked_in`` (403) -- not on the roster, name does not match the mid, or the
  session has ended. Nothing they can fix from our form.
* ``project_required`` (403) -- they ARE checked in, but not as "working on a
  project", or with no project chosen. Fixable in the TinkerHub app in ten seconds,
  and telling them so is the difference between a retry and giving up.
* ``checkin_unavailable`` (503) -- we could not read the roster. Never a denial: see
  `client`.
"""

from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.checkin import client
from apps.checkin.client import CheckinUnavailable
from apps.checkin.eligibility import ELIGIBLE, REASON_PROJECT, REASON_PURPOSE, refusal_reason
from apps.checkin.errors import denied
from apps.checkin.matching import normalize


class CheckinServiceUnavailable(APIException):
    status_code = 503

    def __init__(self):
        # The body is built explicitly rather than left to DRF's default rendering,
        # which emits `{"detail": ...}` with no machine-readable key. The client
        # distinguishes "we could not check" from "you are not checked in" to decide
        # whether retrying is worth offering, so `code` has to be present.
        self.detail = {
            "detail": "Check-in service is unavailable.",
            "code": "checkin_unavailable",
        }


def verify(makerspace, *, mid, typed_name):
    """The roster entry this submission is entitled to act as.

    Returns the `CheckinEntry`. Raises `PermissionDenied` (403) or
    `CheckinServiceUnavailable` (503); never returns None.
    """
    try:
        # Called through the module, never bound by name at import time: a
        # module-level `from ... import fetch_roster` freezes whatever the attribute
        # was when this module was first imported, which for a lazily-imported view
        # module is not a stable moment.
        roster = client.fetch_roster(cached=False)
    except CheckinUnavailable as exc:
        raise CheckinServiceUnavailable() from exc

    entry = next((item for item in roster if item.mid == mid), None)
    if entry is None:
        raise denied("not_checked_in", "You are not currently checked in.")

    # The name is re-checked against the mid so a caller cannot pair someone else's
    # mid with their own name, or vice versa. Both halves have to agree.
    if normalize(entry.name) != normalize(typed_name):
        raise denied("not_checked_in", "You are not currently checked in.")

    reason = refusal_reason(entry, timezone.now(), space_id=makerspace.checkin_space_id)
    if reason in (REASON_PURPOSE, REASON_PROJECT):
        raise denied(
            "project_required",
            "Set your check-in to 'Working on a project' and choose a project, "
            "then try again.",
        )
    if reason != ELIGIBLE:
        # `expired` and `space` both reduce to "not checked in here, now". They are
        # kept distinct internally for logging but must not leak which makerspace a
        # given mid belongs to.
        raise denied("not_checked_in", "You are not currently checked in.")
    return entry
