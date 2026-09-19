"""Budgets for the two unauthenticated check-in surfaces.

The lookup endpoint is the amplification surface: it is unauthenticated and each call
can cause an upstream fetch, so without its own budget a bot turns our public form
into a load generator aimed at a third party's API. It therefore gets a HARDER budget
than submit, and its own scopes -- the existing anonymous-request classes have FIXED
scopes, so putting them on a view with a different `throttle_scope` would silently
reuse the submit budget rather than create a new one.
"""

import hashlib

from rest_framework.throttling import SimpleRateThrottle

from apps.apiclients.throttling import MemberPrincipalRateThrottle
from apps.hardware_requests.throttles import _AnonymousIpThrottle


class CheckinLookupMemberThrottle(MemberPrincipalRateThrottle):
    """Apply the lookup scope only to signed-in member principals."""

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return None
        return super().get_cache_key(request, view)


class CheckinLookupIpBurstThrottle(_AnonymousIpThrottle):
    scope = "checkin_lookup_ip_burst"


class CheckinLookupIpHourThrottle(_AnonymousIpThrottle):
    scope = "checkin_lookup_ip_hour"


class CheckinMidThrottle(SimpleRateThrottle):
    """Per-person budget, so one roster identity cannot flood from rotating IPs.

    Keyed on a DIGEST of makerspace + mid, never the raw mid: cache keys reach
    Redis, `MONITOR`, and any operator with `KEYS *`, and the mid is the one
    directly-identifying value this feature handles. Hashing it costs nothing and
    keeps the identifier out of a store that has none of the protections the
    database column has.
    """

    scope = "checkin_mid"

    def get_cache_key(self, request, view):
        mid = getattr(request, "checkin_mid", None)
        makerspace_id = getattr(request, "checkin_makerspace_id", None)
        if mid is None or makerspace_id is None:
            return None
        digest = hashlib.sha256(f"checkin-mid:v1:{makerspace_id}:{mid}".encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


class CheckinMidUploadThrottle(CheckinMidThrottle):
    """Budget uploads separately because each is one step toward one submission.

    Without its own budget, a multi-file job can throttle itself out before its
    required final submission is able to finish.
    """

    scope = "checkin_mid_upload"
