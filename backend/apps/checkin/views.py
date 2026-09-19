"""The public name-to-roster lookup.

Returns matches for a name the caller ALREADY typed -- never the roster. That
distinction is the privacy posture: the upstream roster is world-readable, so
echoing an entry the caller named discloses nothing new, whereas serving the list
would republish everyone in the building from our own domain.
"""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.checkin import matching
from apps.checkin import client
from apps.checkin.client import CheckinUnavailable
from apps.checkin.eligibility import ELIGIBLE, REASON_SPACE, refusal_reason
from apps.checkin.serializers import (
    CheckinLookupRequestSerializer,
    CheckinMatchSerializer,
)
from apps.checkin.throttles import (
    CheckinLookupIpBurstThrottle,
    CheckinLookupIpHourThrottle,
    CheckinLookupMemberThrottle,
)
from apps.hardware_requests.view_helpers import PUBLIC_ERROR_RESPONSES
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.request_access import checkin_requests_allowed


class CheckinLookupView(APIView):
    permission_classes = [AllowAny]
    # Declared at class level so DRF charges them in `initial()`, BEFORE the handler
    # and before any upstream fetch -- the same discipline `RequestSubmitView`
    # documents at length. Never override `check_throttles`/`get_throttles`.
    # The IP throttles skip authenticated users, so the member throttle closes the
    # signed-in probing path without spending anonymous callers' existing budgets twice.
    throttle_classes = [
        CheckinLookupMemberThrottle,
        CheckinLookupIpBurstThrottle,
        CheckinLookupIpHourThrottle,
    ]
    throttle_scope = "checkin_lookup_ip_burst"

    @extend_schema(
        tags=["Public requests"],
        summary="Find your check-in entry by name",
        request=CheckinLookupRequestSerializer,
        responses={200: CheckinMatchSerializer(many=True), **PUBLIC_ERROR_RESPONSES},
    )
    def post(self, request, makerspace_slug, *args, **kwargs):
        makerspace = get_public_makerspace(makerspace_slug)
        if not checkin_requests_allowed(makerspace):
            # 404 rather than 403: on a makerspace not running this policy the
            # endpoint does not conceptually exist, and saying so would advertise a
            # surface the operator has not enabled.
            return Response(
                {"detail": "Not found.", "code": "not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CheckinLookupRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # Cached: this is a UI affordance, not the authorization decision. Submit
            # refetches without the cache -- see `client.fetch_roster`.
            roster = client.fetch_roster(cached=True)
        except CheckinUnavailable:
            return Response(
                {"detail": "Check-in service is unavailable.", "code": "checkin_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        now = timezone.now()
        space_id = makerspace.checkin_space_id
        matches = []
        for entry in matching.candidates(roster, serializer.validated_data["name"]):
            reason = refusal_reason(entry, now, space_id=space_id)
            if reason == REASON_SPACE:
                # Discarded, not reported. The roster is deployment-global, so an entry
                # bound to another upstream spaceId belongs to a different makerspace;
                # returning it here would republish that space's mid, display name,
                # avatar, purpose and project name through this tenant's endpoint.
                # docs/INVARIANTS.md: "Entries whose spaceId does not match are discarded."
                continue
            matches.append(
                {
                    "mid": entry.mid,
                    "name": entry.name,
                    "avatar": entry.avatar,
                    "purpose": entry.purpose,
                    "project_name": entry.project_name,
                    "eligible": reason == ELIGIBLE,
                    "reason": reason,
                }
            )
        return Response(CheckinMatchSerializer(matches, many=True).data)
