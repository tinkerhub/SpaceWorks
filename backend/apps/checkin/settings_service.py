"""A makerspace's own check-in settings: read, write and test.

The console's Check-in card is the only caller. Three rules shape it:

* **`request_access.set_request_access` stays the only writer of the mode.** This module
  writes the roster fields and the space binding, then hands any mode change to it, so
  the membership-wins rule, its row lock and its `makerspace.request_access_changed`
  audit apply exactly as they do from the CLI.
* **No external I/O under the row lock.** The save-time SSRF check resolves DNS, so the
  serializer runs it before this module takes the lock (the payments-settings rule).
* **The test button never 5xxs and never echoes the upstream body.** It answers
  `{ok, rows, code, reason}` with a sentence an operator can act on.
"""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.checkin import client, transport
from apps.checkin.config import (
    CheckinConfig,
    checkin_config,
    deployment_provider,
    deployment_purpose,
    deployment_url,
)
from apps.checkin.transport import CheckinUnavailable
from apps.makerspaces import request_access

ROSTER_FIELDS = ("checkin_api_url", "checkin_required_purpose", "checkin_provider_name")
EDITABLE_FIELDS = (*ROSTER_FIELDS, "checkin_space_id")

TEST_REASONS = {
    transport.REASON_NOT_CONFIGURED: "No roster URL is set here or for the deployment.",
    transport.REASON_REFUSED: (
        "That address is private, internal or not https, so it was not contacted."
    ),
    transport.REASON_UNREACHABLE: "The roster couldn't be reached. Check the URL.",
    transport.REASON_TIMEOUT: "The roster didn't answer in time.",
    transport.REASON_TLS: "The secure connection to the roster failed.",
    transport.REASON_STATUS: "The roster answered with an error status.",
    transport.REASON_REDIRECT: (
        "The roster answered with a redirect. Use the final URL; redirects are not followed."
    ),
    transport.REASON_TOO_LARGE: "The roster is larger than this server accepts.",
    client.REASON_NOT_JSON: "The roster didn't answer with JSON.",
    client.REASON_NOT_ARRAY: "The roster's JSON isn't a list of check-ins.",
    client.REASON_TOO_MANY_ROWS: "The roster has more rows than this server accepts.",
    client.REASON_UNPARSEABLE: "None of the roster's rows could be read.",
}
GENERIC_REASON = "The roster couldn't be read."


def settings_payload(makerspace):
    effective = checkin_config(makerspace)
    return {
        "public_request_mode": makerspace.public_request_mode,
        "request_access": request_access.effective_policy(makerspace),
        "membership_installed": request_access.membership_installed(
            makerspace.enabled_modules
        ),
        "checkin_space_id": makerspace.checkin_space_id,
        "checkin_api_url": makerspace.checkin_api_url,
        "checkin_required_purpose": makerspace.checkin_required_purpose,
        "checkin_provider_name": makerspace.checkin_provider_name,
        "deployment": {
            "api_url": deployment_url(),
            "required_purpose": deployment_purpose(),
            "provider_name": deployment_provider(),
        },
        "effective": {
            "api_url_source": (
                "makerspace" if effective.tenant_url else "deployment" if effective.url else ""
            ),
            "required_purpose": effective.purpose,
            "provider_name": effective.provider,
        },
    }


def update_settings(makerspace, data, *, actor):
    """Apply validated `data` (any of EDITABLE_FIELDS + `public_request_mode`)."""
    from apps.makerspaces.models import Makerspace

    mode = data.get("public_request_mode")
    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        changes = {
            field: data[field]
            for field in EDITABLE_FIELDS
            if field in data and getattr(locked, field) != data[field]
        }
        final_mode = mode if mode is not None else locked.public_request_mode
        if final_mode == request_access.MODE_CHECKED_IN:
            _require_usable(locked, changes)
        leaving_checkin = mode is not None and mode != request_access.MODE_CHECKED_IN
        if leaving_checkin:
            # First, so clearing the space binding cannot trip the
            # checked-in-requires-space-id constraint on the way out.
            _set_mode(locked, mode, actor)
        if changes:
            for field, value in changes.items():
                setattr(locked, field, value)
            locked.save(update_fields=[*changes, "updated_at"])
        if mode is not None and not leaving_checkin:
            _set_mode(locked, mode, actor)
        if changes:
            audit.record(
                actor,
                "checkin.settings_updated",
                makerspace=locked,
                target=locked,
                # Field names only: a roster URL can carry a query-string token.
                meta={"fields": sorted(changes)},
            )
    locked.refresh_from_db()
    return locked


def _require_usable(locked, changes):
    space_id = changes.get("checkin_space_id", locked.checkin_space_id)
    if space_id is None or space_id <= 0:
        raise ValidationError(
            {"checkin_space_id": "Check-in needs this makerspace's upstream space ID."}
        )
    url = changes.get("checkin_api_url", locked.checkin_api_url)
    if not (url or deployment_url()):
        raise ValidationError(
            {"checkin_api_url": "Check-in needs a roster URL; this deployment has no default."}
        )


def _set_mode(locked, mode, actor):
    try:
        request_access.set_request_access(locked, mode, actor=actor)
    except request_access.RequestAccessConflict as exc:
        raise ValidationError({"public_request_mode": str(exc)}) from exc


def test_connection(makerspace, candidate_url=""):
    """Read the roster once, uncached, and describe the result. Never raises."""
    saved = checkin_config(makerspace)
    if candidate_url:
        # Typed into the form, so attacker-influenced exactly like a saved URL.
        config = CheckinConfig(
            url=candidate_url, purpose=saved.purpose, provider="", tenant_url=True
        )
    else:
        config = saved
    try:
        entries = client._parse(transport.fetch_body(config))
    except CheckinUnavailable as exc:
        return {
            "ok": False,
            "rows": 0,
            "space_rows": None,
            "code": exc.reason,
            "reason": TEST_REASONS.get(exc.reason, GENERIC_REASON),
        }
    space_id = makerspace.checkin_space_id
    return {
        "ok": True,
        "rows": len(entries),
        # Rows the gate could admit here; None until a space ID is bound.
        "space_rows": (
            None
            if space_id is None
            else sum(1 for entry in entries if entry.space_id == space_id)
        ),
        "code": "",
        "reason": "",
    }
