"""The TinkerHub active-check-in roster, fetched and parsed fail-closed.

`GET <roster URL>` (the makerspace's own, else `CHECKIN_API_URL`; resolved by
`config.checkin_config`, fetched by `transport`) returns a JSON array of everyone
currently checked in at one upstream space. It is a PUBLIC endpoint: no API key, no per-user token, no query
filters. That shapes every decision here.

**Only a well-formed 2xx list is ever trusted.** Unlike the retired pre-M7 client
(`73a480c^:backend/apps/checkin/client.py`), this endpoint returns a roster rather
than a verdict, so there is no status code that means "denied". A 404, a 500, an
HTML error page and a timeout are all the same thing -- we do not know who is
checked in -- and all raise `CheckinUnavailable`, which the views map to 503. A
denial (403) is only ever derived from a roster we successfully read.

The distinction that matters most: a MALFORMED response and an EMPTY one are not
the same. Nobody being checked in is a normal Tuesday morning and must read as
"not checked in". A body we could not parse is a broken contract and must read as
503, because reporting it as "not checked in" would tell a requester standing in
the building that they are not in the building.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime

from django.core.cache import cache

from apps.checkin import transport
from apps.checkin.config import checkin_config
from apps.checkin.transport import REASON_NOT_CONFIGURED, CheckinUnavailable

logger = logging.getLogger(__name__)

__all__ = ["CheckinEntry", "CheckinUnavailable", "fetch_roster"]

CACHE_KEY = "checkin:active-roster"

REASON_NOT_JSON = "not_json"
REASON_NOT_ARRAY = "not_array"
REASON_TOO_MANY_ROWS = "too_many_rows"
REASON_UNPARSEABLE = "unparseable"

# Field ceilings. Upstream is a third party we do not control, so every string that
# reaches a database column or a response body is bounded here rather than trusted.
MAX_NAME = 200
MAX_PURPOSE = 200
MAX_PROJECT = 200
MAX_AVATAR = 500
# `mid` crosses the generated browser client as a JSON number. Values above this
# boundary can be rounded before confirmation, changing the identity the server verifies.
MAX_MID = (1 << 53) - 1


@dataclass(frozen=True, slots=True)
class CheckinEntry:
    mid: int
    name: str
    avatar: str
    purpose: str
    project_name: str
    check_in_time: datetime | None
    check_out_time: datetime | None
    space_id: int | None


def fetch_roster(makerspace=None, *, cached: bool):
    """The active roster for `makerspace`'s resolved upstream (`config.checkin_config`).

    `cached=True` serves a short-lived shared copy and is for the LOOKUP surface,
    which is an unauthenticated UI affordance and would otherwise let a bot turn
    our public form into an amplifier against a third party's API.

    `cached=False` is mandatory wherever the roster is the authorization fact --
    submit, checkout, return. A cached copy can outlive a checkout, and "checked in
    within the last 30 seconds" is not the rule we promised.

    The cache is keyed by the RESOLVED URL, never shared across upstreams: with
    per-makerspace rosters one key would serve one space's checked-in people to
    another space's lookup.
    """
    config = checkin_config(makerspace)
    if not config.ready:
        # No roster, or no purpose to require (a blank purpose would match only
        # blank-purpose rows -- an accident, not a policy). Fail closed.
        raise CheckinUnavailable(
            "Check-in service is not configured.", reason=REASON_NOT_CONFIGURED
        )
    key = cache_key(config.url)
    if cached:
        hit = cache.get(key)
        if isinstance(hit, list):
            return hit
    entries = _parse(transport.fetch_body(config))
    if cached:
        cache.set(key, entries, transport.setting("CHECKIN_CACHE_SECONDS", 30))
    return entries


def cache_key(url):
    # A digest, not the URL: a cache key reaches Redis `MONITOR`/`KEYS *`, and a
    # roster URL may carry a query-string token.
    return f"{CACHE_KEY}:{hashlib.sha256(url.encode()).hexdigest()}"


def _get_body(config=None):
    """The raw body for `config` (default: the deployment's). Kept for callers/tests."""
    return transport.fetch_body(config or checkin_config())


def _parse(body):
    try:
        data = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise CheckinUnavailable(
            "Check-in roster was not valid JSON.", reason=REASON_NOT_JSON
        ) from exc
    # The upstream answers a literal JSON `null` (not `[]`) while nobody is checked in.
    # That is its empty roster, not an outage; any other non-array body still fails closed.
    if data is None:
        data = []
    if not isinstance(data, list):
        raise CheckinUnavailable(
            "Check-in roster was not a JSON array.", reason=REASON_NOT_ARRAY
        )

    max_rows = transport.setting("CHECKIN_MAX_ROWS", 2000)
    if len(data) > max_rows:
        raise CheckinUnavailable(
            "Check-in roster had too many rows.", reason=REASON_TOO_MANY_ROWS
        )

    entries = []
    skipped = 0
    for row in data:
        entry = _entry(row)
        if entry is None:
            skipped += 1
            continue
        entries.append(entry)

    # One unparseable row must not deny everyone else -- but a body where nothing
    # parsed is a contract change, not a quiet Tuesday, and must surface as 503
    # rather than as a confident "you are not checked in".
    if data and not entries:
        logger.warning("Check-in roster had no parseable rows.", extra={"rows": len(data)})
        raise CheckinUnavailable(
            "Check-in roster could not be parsed.", reason=REASON_UNPARSEABLE
        )
    if skipped:
        logger.warning(
            "Check-in roster had unparseable rows.",
            extra={"skipped": skipped, "kept": len(entries)},
        )
    return _drop_ambiguous(entries)


def _drop_ambiguous(entries):
    """Remove every entry whose `mid` is not unique in this response.

    A repeated mid makes identity ambiguous: two rows claim the same person with
    possibly different projects, and picking either would be a guess about who is
    accountable for a tool. Dropping only the affected mid fails closed for exactly
    those people instead of denying the whole building.
    """
    seen = {}
    for entry in entries:
        seen[entry.mid] = seen.get(entry.mid, 0) + 1
    duplicated = {mid for mid, count in seen.items() if count > 1}
    if duplicated:
        logger.warning("Check-in roster had duplicate mids.", extra={"count": len(duplicated)})
    return [entry for entry in entries if entry.mid not in duplicated]


def _entry(row):
    if not isinstance(row, dict):
        return None
    mid = row.get("mid")
    if not isinstance(mid, int) or isinstance(mid, bool) or not (0 < mid <= MAX_MID):
        return None
    name = _text(row.get("name"), MAX_NAME)
    if not name.strip():
        # A nameless entry can never be matched, and matching is the whole of
        # identity here. Keeping it would only ever produce a confusing near-miss.
        return None
    space_id = row.get("spaceId")
    # bool subclasses int in Python; accepting True would cross-match space 1.
    if not isinstance(space_id, int) or isinstance(space_id, bool):
        space_id = None
    return CheckinEntry(
        mid=mid,
        name=name,
        avatar=_text(row.get("avatar"), MAX_AVATAR),
        purpose=_text(row.get("purpose"), MAX_PURPOSE),
        project_name=_text(row.get("projectName"), MAX_PROJECT),
        check_in_time=_moment(row.get("checkInTime")),
        check_out_time=_moment(row.get("checkOutTime")),
        space_id=space_id,
    )


def _text(value, limit):
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    return value[:limit]


def _moment(value):
    """Parse an upstream timestamp, or None.

    Returning None rather than raising keeps a row with one bad timestamp usable
    for LOOKUP; `eligibility` treats a missing checkout as non-expiring, which is
    safe only because the endpoint itself only lists active sessions and submit
    always refetches.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        # A naive upstream timestamp cannot be compared against an aware `now`
        # without inventing a timezone, and guessing one would silently shift a
        # checkout window. Treat it as absent instead.
        return None
    return moment
