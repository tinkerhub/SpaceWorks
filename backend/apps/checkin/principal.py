"""Resolve the acting principal for public surfaces using the check-in policy.

The public roster is a presence filter, not authentication. Every calling surface
must charge its per-mid throttle and check idempotency before calling this seam,
because fresh-roster verification here is the only upstream-dependent step.
"""

from dataclasses import dataclass

from rest_framework.exceptions import ValidationError

from apps.checkin import identity, verification
from apps.makerspaces import request_access

__all__ = ["resolve_request_principal"]


@dataclass(frozen=True, slots=True)
class _RequestPrincipal:
    entry: object
    identity: object

    @property
    def user(self):
        """The local user that acts as this check-in principal."""
        return self.identity.user


def resolve_request_principal(makerspace, request, *, mid, typed_name):
    """Resolve a checked-in caller, or leave non-check-in policies unchanged."""
    if not request_access.checkin_requests_allowed(makerspace):
        return None
    if mid is None:
        raise ValidationError({"checkin_mid": "This field is required."})
    if not isinstance(typed_name, str) or not typed_name.strip():
        raise ValidationError({"name": "This field is required."})

    entry = verification.verify(makerspace, mid=mid, typed_name=typed_name)
    resolved_identity = identity.resolve_principal(makerspace, entry)
    return _RequestPrincipal(entry=entry, identity=resolved_identity)
