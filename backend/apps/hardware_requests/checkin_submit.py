"""The `checked_in` branch of public borrow submission.

Its own module because `public_views.py` sits at the repo's ~300-line hard ceiling,
and the rule is to split before adding rather than after.

**Ordering is the security property here**, and it is the same discipline
`RequestSubmitView` documents for its anonymous branch: everything local and cheap
runs before the one expensive, externally-dependent step.

    IP throttle (charged by DRF in `initial()`)
      -> policy refusal
      -> honeypot
      -> serializer
      -> per-mid throttle
      -> idempotency replay
      -> product validation
      -> FRESH roster verification      <-- the only upstream call
      -> principal resolution
      -> workflow

Replay lookup precedes the upstream call deliberately: a legitimate retry of a
request we already accepted must still succeed after the person has checked out, and
must not fail merely because the roster is unreachable right now. Verifying first
would make a successful submission un-retryable the moment either changed.
"""

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.accounts.audit_events import fingerprint
from apps.checkin import verification
from apps.checkin.identity import resolve_principal
from apps.checkin.throttles import CheckinMidThrottle
from apps.hardware_requests.request_workflow import RequesterSnapshot


def require_mid(data):
    mid = data.get("checkin_mid")
    if mid is None:
        raise ValidationError({"checkin_mid": "This field is required."})
    return mid


def charge_mid_throttle(
    request,
    view,
    makerspace,
    mid,
    enforce,
    *,
    throttles=(CheckinMidThrottle,),
):
    """Budget the verified person before anything upstream is touched.

    The mid is stamped onto the request rather than passed, because DRF throttles
    only receive `(request, view)`.
    """
    request.checkin_mid = mid
    request.checkin_makerspace_id = makerspace.id
    enforce(request, view, throttles)


def payload_fingerprint(data, mid):
    """Idempotency payload identity for this branch.

    `mid` is part of it on purpose. Two people who share a display name would
    otherwise produce identical fingerprints for identical item lists, and one
    could replay the other's request -- returning them someone else's public token.
    """
    import json

    canonical = {
        "checkin_mid": mid,
        "requested_for": data.get("requested_for", ""),
        "items": sorted(
            (item["product_id"], item["quantity"]) for item in data["items"]
        ),
    }
    return fingerprint(json.dumps(canonical, sort_keys=True, separators=(",", ":")))


def verify_and_resolve(makerspace, *, mid, typed_name):
    """Fresh-roster verification, then the durable per-person principal."""
    entry = verification.verify(makerspace, mid=mid, typed_name=typed_name)
    identity = resolve_principal(makerspace, entry)
    return entry, identity


def snapshot(entry, identity):
    """Identity captured on the request.

    The CANONICAL roster name is stored, never the caller's spelling: matching is
    normalised (case, spacing), so "ada  example" matches and must not become the
    name a staffer reads off the review card.

    `contact_verified` stays False. The check-in match verifies PRESENCE, not contact
    details -- and setting it True would additionally route this submission around
    the anonymous idempotency and outstanding-limit path in `submit_request`.

    `checkin_purpose` stores the CONFIGURED canonical literal rather than the raw
    upstream string, so the column cannot drift into per-person free text if the
    gate is ever relaxed.
    """
    return RequesterSnapshot(
        username="",
        name=entry.name,
        email="",
        phone="",
        contact_verified=False,
        checkin_identity=identity,
        checkin_purpose=settings.CHECKIN_REQUIRED_PURPOSE,
        checkin_project_name=entry.project_name.strip(),
    )
