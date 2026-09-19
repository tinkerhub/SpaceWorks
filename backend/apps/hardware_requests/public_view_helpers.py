"""Shared helpers for the public borrow-request surface.

Split out of `public_views.py` when it reached the repo's ~300-line hard ceiling. The
views keep their names and import from here; nothing else moved.
"""

import json
import uuid
from types import SimpleNamespace

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.response import Response

from apps.accounts.audit_events import fingerprint
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.serializers import RequestSubmitResponseSerializer
from apps.inventory.models import InventoryProduct
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_queryset


def _idempotency_fingerprint(request):
    """The `Idempotency-Key` header, validated, as a fingerprint.

    Shared by both account-less branches: each needs a retry of an accepted
    submission to return the ORIGINAL request rather than create a second one, and
    two copies of this rule would be two chances to drift.
    """
    idempotency_key = str(request.headers.get("Idempotency-Key", "")).strip()
    if not idempotency_key:
        raise ValidationError(
            {"idempotency_key": "This header is required for account-less submissions."}
        )
    if len(idempotency_key) > settings.ANONYMOUS_REQUEST_IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ValidationError(
            {
                "idempotency_key": (
                    "Ensure this header has no more than "
                    f"{settings.ANONYMOUS_REQUEST_IDEMPOTENCY_KEY_MAX_LENGTH} characters."
                )
            }
        )
    return fingerprint(idempotency_key)


def _honeypot_response():
    decoy = SimpleNamespace(
        public_token=uuid.uuid4(),
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    return Response(
        RequestSubmitResponseSerializer(decoy).data,
        status=status.HTTP_201_CREATED,
    )


def _enforce_throttles(request, view, throttle_types):
    waits = []
    for throttle_type in throttle_types:
        throttle = throttle_type()
        if not throttle.allow_request(request, view):
            waits.append(throttle.wait())
    if waits:
        durations = [wait for wait in waits if wait is not None]
        raise Throttled(wait=max(durations) if durations else None)


def _anonymous_payload_fingerprint(data):
    canonical = {
        "contact_email": data["contact_email"],
        "contact_name": data["contact_name"].strip(),
        "contact_phone": data.get("contact_phone", ""),
        "items": sorted(data["items"], key=lambda item: item["product_id"]),
        "requested_for": data["requested_for"],
    }
    return fingerprint(json.dumps(canonical, sort_keys=True, separators=(",", ":")))


def _honeypot_filled(payload):
    """True if the hidden anti-spam `website` field was populated. Real browsers never
    fill it; bots that auto-fill every field do. Read defensively from the raw payload."""
    try:
        value = payload.get("website", "")
    except AttributeError:
        return False
    return bool(str(value).strip())


def _requestable_products(product_ids, makerspace):
    return {
        product.pk: product
        for product in InventoryProduct.objects.filter(
            pk__in=product_ids,
            makerspace=makerspace,
            is_public=True,
            is_archived=False,
        )
    }


def _require_module(makerspace, module_key):
    if not module_enabled(makerspace, module_key):
        raise ValidationError({"module": f"{module_key} is disabled for this makerspace."})
