"""Invalid protocol values, applied to real persisted auth fixtures."""
from uuid import uuid4

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.models_devices import DeviceGrant, DeviceRefreshFamily, NativeAppRegistration
from apps.makerspaces.models import MakerspaceMembership
from tests.qr_target_safety_helpers import membership

from .auth_setup import authenticate

REFUSALS = (
    ("generation", 401, "different authentication generation"),
    ("unknown-surface", 401, "Invalid session surface"),
    ("member-surface", 403, "Member sessions cannot access staff APIs"),
    ("missing-surface", 403, "Member sessions cannot access staff APIs"),
    ("staff-origin", 403, "trusted staff origin"),
    ("staff-scope", 403, "Staff session origin does not match"),
    ("missing-grant", 403, "requires a device grant"),
    ("missing-family", 401, "Invalid device authorization"),
    ("unknown-family", 401, "Device authorization is no longer active"),
    ("revoked-grant", 401, "Device authorization is no longer active"),
    ("revoked-registration", 401, "Device authorization is no longer active"),
    ("revoked-family", 401, "Device authorization is no longer active"),
    ("wrong-family-user", 401, "Device authorization is no longer active"),
    ("wrong-grant-user", 401, "Device authorization is no longer active"),
    ("invalid-selection", 403, "Invalid native makerspace selection"),
    ("nonmember-selection", 403, "Makerspace selection is not available"),
    ("conflicting-selection", 403, "target does not match the selected makerspace"),
    ("browser-selection", 403, "Browser origin cannot use native makerspace selection"),
    ("origin-selection-conflict", 403, "Makerspace selection conflicts with browser origin"),
    ("unverified", 403, "Verify the account email"),
    ("inactive", 401, "User is inactive"),
    ("suspended", 401, "Device authorization is no longer active"),
    ("must-change-password", 403, "permission"),
)


def deny(session, lab, kind):
    token, defaults = session.token, session.client.defaults
    if kind == "generation":
        token["auth_generation"] = str(uuid4())
    elif kind == "unknown-surface":
        token["surface"] = "not-a-session-surface"
    elif kind == "member-surface":
        token["surface"] = "member"
    elif kind == "missing-surface":
        del token["surface"]
    elif kind in {"staff-origin", "staff-scope"}:
        token["surface"], token["staff_scope"] = "staff", str(lab.other.pk)
        defaults["HTTP_ORIGIN"] = ("https://untrusted.example.test" if kind == "staff-origin"
                                   else f"https://{lab.home.frontend_domain}")
    elif kind == "missing-grant":
        del token["device_grant_id"]
    elif kind == "missing-family":
        del token["device_family_id"]
    elif kind == "unknown-family":
        token["device_family_id"] = str(uuid4())
    elif kind == "revoked-grant":
        DeviceGrant.objects.filter(pk=session.grant.pk).update(status=DeviceGrant.Status.REVOKED)
    elif kind == "revoked-registration":
        NativeAppRegistration.objects.filter(pk=session.registration.pk).update(
            status=NativeAppRegistration.Status.REVOKED,
        )
    elif kind == "revoked-family":
        DeviceRefreshFamily.objects.filter(pk=session.family.pk).update(revoked_at=timezone.now())
    elif kind == "wrong-family-user":
        DeviceRefreshFamily.objects.filter(pk=session.family.pk).update(user=lab.root)
    elif kind == "wrong-grant-user":
        DeviceGrant.objects.filter(pk=session.grant.pk).update(user=lab.root)
    elif kind == "invalid-selection":
        defaults["HTTP_X_MAKERSPACE_ID"] = "01"
    elif kind in {"nonmember-selection", "conflicting-selection"}:
        if kind == "conflicting-selection":
            membership(lab.actor, lab.other)
        defaults["HTTP_X_MAKERSPACE_ID"] = str(lab.other.pk)
    elif kind == "browser-selection":
        defaults["HTTP_ORIGIN"] = "https://untrusted.example.test"
    elif kind == "origin-selection-conflict":
        defaults["HTTP_ORIGIN"] = f"https://{lab.other.frontend_domain}"
    elif kind == "unverified":
        User.objects.filter(pk=lab.actor.pk).update(self_registered_at=timezone.now(), email_verified_at=None)
    elif kind == "inactive":
        User.objects.filter(pk=lab.actor.pk).update(is_active=False)
    elif kind == "suspended":
        User.objects.filter(pk=lab.actor.pk).update(access_status=User.AccessStatus.SUSPENDED)
    elif kind == "must-change-password":
        User.objects.filter(pk=lab.actor.pk).update(must_change_password=True)
    else:
        raise AssertionError(kind)
    authenticate(session)


def protocol_rows():
    from .assertions import all_rows
    from .auth_setup import AUTH_MODELS

    return all_rows(User, MakerspaceMembership, *AUTH_MODELS)
