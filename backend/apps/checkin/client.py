"""The TinkerHub active-check-in roster, fetched and parsed fail-closed.

`GET <CHECKIN_API_URL>` returns a JSON array of everyone currently checked in at one
upstream space. It is a PUBLIC endpoint: no API key, no per-user token, no query
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

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = "checkin:active-roster"

# Field ceilings. Upstream is a third party we do not control, so every string that
# reaches a database column or a response body is bounded here rather than trusted.
MAX_NAME = 200
MAX_PURPOSE = 200
MAX_PROJECT = 200
MAX_AVATAR = 500
# `mid` crosses the generated browser client as a JSON number. Values above this
# boundary can be rounded before confirmation, changing the identity the server verifies.
MAX_MID = (1 << 53) - 1


class CheckinUnavailable(Exception):
    """We could not establish who is checked in. Always maps to 503, never 403."""


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


def fetch_roster(*, cached: bool):
    """The active roster.

    `cached=True` serves a short-lived shared copy and is for the LOOKUP surface,
    which is an unauthenticated UI affordance and would otherwise let a bot turn
    our public form into an amplifier against a third party's API.

    `cached=False` is mandatory wherever the roster is the authorization fact --
    submit, checkout, return. A cached copy can outlive a checkout, and "checked in
    within the last 30 seconds" is not the rule we promised.
    """
    if cached:
        hit = cache.get(CACHE_KEY)
        if isinstance(hit, list):
            return hit
    entries = _parse(_get_body())
    if cached:
        cache.set(CACHE_KEY, entries, _setting("CHECKIN_CACHE_SECONDS", 30))
    return entries


def _setting(name, default):
    value = getattr(settings, name, default)
    return default if value is None else value


def _get_body():
    import requests

    url = getattr(settings, "CHECKIN_API_URL", "")
    if not url:
        # Reaching here means a tenant is in `checked_in` mode on a deployment that
        # never configured the roster. Fail closed rather than admit everyone.
        raise CheckinUnavailable("Check-in service is not configured.")
    max_bytes = _setting("CHECKIN_MAX_RESPONSE_BYTES", 1_048_576)
    try:
        response = requests.get(
            url,
            timeout=_setting("CHECKIN_TIMEOUT", 5.0),
            stream=True,
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            logger.warning(
                "Check-in roster returned an unsuccessful status.",
                extra={"status_code": response.status_code},
            )
            raise CheckinUnavailable("Check-in service is unavailable.")
        declared = int(response.headers.get("Content-Length") or 0)
        if not response.headers.get("Content-Encoding") and declared > max_bytes:
            raise CheckinUnavailable("Check-in roster is too large.")
        chunks = []
        size = 0
        # requests asks urllib3 to decode Content-Encoding while iterating. Enforce
        # the ceiling on those decoded bytes, not the smaller compressed wire body.
        for chunk in response.iter_content(chunk_size=min(65_536, max_bytes + 1)):
            if not chunk:
                continue
            if len(chunk) > max_bytes - size:
                raise CheckinUnavailable("Check-in roster is too large.")
            chunks.append(chunk)
            size += len(chunk)
        body = b"".join(chunks)
    except CheckinUnavailable:
        raise
    except Exception as exc:
        # `requests` raises a wide family here (ConnectionError, Timeout, SSLError,
        # ChunkedEncodingError, and response-decoding errors). They all
        # mean the same thing to us, and none of them may become a denial.
        logger.warning(
            "Check-in roster fetch failed.",
            extra={"error_class": type(exc).__name__},
        )
        raise CheckinUnavailable("Check-in service is unavailable.") from exc
    return body


def _parse(body):
    try:
        data = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise CheckinUnavailable("Check-in roster was not valid JSON.") from exc
    if not isinstance(data, list):
        raise CheckinUnavailable("Check-in roster was not a JSON array.")

    max_rows = _setting("CHECKIN_MAX_ROWS", 2000)
    if len(data) > max_rows:
        raise CheckinUnavailable("Check-in roster had too many rows.")

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
        raise CheckinUnavailable("Check-in roster could not be parsed.")
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
