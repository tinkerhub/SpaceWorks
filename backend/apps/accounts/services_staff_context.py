"""Minimal browser staff discovery; authorization still belongs to existing guards."""

from django.conf import settings

from apps.accounts import rbac
from apps.accounts.models import User
from apps.accounts.social_nonces import request_origin
from apps.makerspaces.cors import staff_origin_is_registered
from apps.makerspaces.domain_verification import is_self_host
from apps.makerspaces.origin_scope import (
    AMBIGUOUS_STAFF_ORIGIN_SCOPE,
    NO_STAFF_ORIGIN_SCOPE,
    staff_origin_scope,
)
from apps.separability.registry import runtime_active


def with_staff_context(payload, user, request, staff_surface):
    # Issuers pass their EFFECTIVE validated surface; /auth/me passes request.auth's.
    # Other user_payload callers deliberately omit it, even for a global identity.
    if (
        request is None
        or staff_surface != "staff"
        or getattr(request, "device_grant", None)
        or getattr(user, "_claim_audit_context", None) is not None
        or (user.self_registered_at and user.email_verified_at is None)
    ):
        return payload
    origin = request_origin(request)
    if not staff_origin_is_registered(origin):
        return payload
    scope = staff_origin_scope(request)
    if scope is AMBIGUOUS_STAFF_ORIGIN_SCOPE:
        return payload
    # NO_STAFF_ORIGIN_SCOPE alone also describes arbitrary, unregistered origins.
    platform_origin = origin in set(settings.PLATFORM_STAFF_ORIGINS)
    if scope is NO_STAFF_ORIGIN_SCOPE and not platform_origin:
        return payload
    managed = not is_self_host()
    payload["staff_context"] = {
        "scope_kind": "platform" if platform_origin else "makerspace",
        "makerspace_id": None if platform_origin else scope,
        "can_manage_platform": bool(
            platform_origin
            and user.is_active
            and user.access_status == User.AccessStatus.ACTIVE
            and not user.must_change_password
            and rbac.can(user, rbac.Action.MANAGE_MAKERSPACE)
        ),
        "platform_hosting": managed,
        "platform_stripe_connect_available": managed and runtime_active("payments"),
    }
    return payload
