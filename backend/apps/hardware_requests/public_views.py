import json
import uuid
from types import SimpleNamespace

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotAuthenticated, Throttled, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.audit_events import fingerprint
from apps.apiclients.throttling import ClientTierRateThrottle, MemberPrincipalRateThrottle
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.request_workflow import (
    RequesterSnapshot,
    anonymous_idempotency_replay,
)
from apps.hardware_requests.serializers import (
    PublicRequestStatusSerializer,
    RequestSubmitResponseSerializer,
    RequestSubmitSerializer,
)
from apps.hardware_requests.throttles import (
    AnonymousRequestEmailThrottle,
    AnonymousRequestIpBurstThrottle,
    AnonymousRequestIpHourThrottle,
)
from apps.hardware_requests.view_helpers import (
    ERROR_404,
    PUBLIC_ERROR_RESPONSES,
    request_queryset,
)
from apps.inventory.models import InventoryProduct
from apps.makerspaces.anonymous_requesters import get_or_create_anonymous_requester
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.request_access import (
    anonymous_requests_allowed,
    checkin_requests_allowed,
)
from apps.hardware_requests import checkin_submit
from apps.hardware_requests.public_view_helpers import (
    _anonymous_payload_fingerprint,
    _enforce_throttles,
    _honeypot_filled,
    _honeypot_response,
    _idempotency_fingerprint,
    _require_module,
    _requestable_products,
)
from apps.makerspaces.servability import servable_queryset
from apps.presence.guard import require_active_account, require_active_member_presence
from apps.openapi import (
    PUBLIC_API_AUTH_PARAMETERS,
    PUBLIC_REQUEST_STATUS_EXAMPLE,
    PUBLIC_REQUEST_SUBMIT_EXAMPLE,
)


class RequestSubmitView(APIView):
    permission_classes = [AllowAny]
    # Every IP/principal budget is declared here so DRF applies it in APIView.initial(),
    # BEFORE the handler runs. `check_throttles` is deliberately NOT overridden: it is a
    # pre-auth lifecycle hook, `apps.accounts.claim_route_guard` refuses any route that
    # replaces one, and overriding it here had already cost the endpoint its floor --
    # anonymous throttles were selected inside post(), which is *after* the
    # `anonymous_requests_allowed` refusal, so every makerspace that had not opted in
    # served an UNTHROTTLED 401 that still paid for a makerspace lookup.
    #
    # Each class self-selects by auth state (see `_AnonymousIpThrottle`), so listing them
    # together does not double-charge anyone. Consequence worth knowing: the honeypot no
    # longer precedes the IP budget, so a bot loud enough to exhaust it sees 429 instead
    # of the honeypot's fake success. Being rate-limited before being fingerprinted is
    # the safer of the two, and the honeypot still absorbs every bot under the limit.
    throttle_classes = [
        MemberPrincipalRateThrottle,
        AnonymousRequestIpBurstThrottle,
        AnonymousRequestIpHourThrottle,
    ]
    throttle_scope = "public_request_submit"

    @extend_schema(
        tags=["Public requests"],
        summary="Submit public borrow request",
        auth=[{"jwtAuth": []}, {}],
        parameters=[
            *PUBLIC_API_AUTH_PARAMETERS,
            OpenApiParameter(
                name="Idempotency-Key",
                type=str,
                location=OpenApiParameter.HEADER,
                required=False,
                description=(
                    "Required for account-less submissions. Reusing a key with the same "
                    "payload returns the original request; a different payload is rejected."
                ),
            ),
        ],
        request=RequestSubmitSerializer,
        responses={201: RequestSubmitResponseSerializer, **PUBLIC_ERROR_RESPONSES},
        examples=[PUBLIC_REQUEST_SUBMIT_EXAMPLE],
    )
    def post(self, request, makerspace_slug, *args, **kwargs):
        makerspace = get_public_makerspace(makerspace_slug)
        unauthenticated = not request.user.is_authenticated
        # `checked_in` and `anyone` are mutually exclusive stored modes, so at most
        # one of these is ever true. Both take their branch BEFORE any membership
        # guard, which is exactly why `request_access` makes the pair unrepresentable.
        checked_in_policy = checkin_requests_allowed(makerspace)
        authenticated_member = bool(
            checked_in_policy
            and not unauthenticated
            and request.user.pk
            and request.user.makerspace_memberships.filter(
                makerspace=makerspace, status="active"
            ).exists()
        )
        if authenticated_member:
            # Membership bypasses only the public roster, never the account-state
            # guard. Restricted, suspended, or inactive users remain blocked.
            require_active_account(request.user, makerspace)
        # A deployment-wide account is not tenant membership; only an active member
        # may bypass the roster selected by this makerspace.
        checkin_submission = checked_in_policy and not authenticated_member
        anonymous_submission = unauthenticated and not checkin_submission
        if checkin_submission:
            if _honeypot_filled(request.data):
                return _honeypot_response()
            _require_module(makerspace, "request_workflow")
        elif anonymous_submission:
            if not anonymous_requests_allowed(makerspace):
                # Raising DRF's own exception preserves the previous IsAuthenticated
                # response body as well as its 401 status for every non-opted-in space.
                #
                # `anonymous_requests_allowed` re-derives the answer rather than reading
                # the column, so a row that somehow carries BOTH the flag and the
                # `membership` module -- raw SQL, an old backup, a restore that predates
                # the model rule -- still fails closed here instead of admitting a
                # stranger past the membership requirement.
                raise NotAuthenticated()
            # Resolving the opt-in flag is unavoidable because disabled spaces must
            # retain their 401. The IP budgets were already charged in initial(); from
            # here the raw honeypot precedes module checks, serializer work, product
            # queries and principal creation.
            if _honeypot_filled(request.data):
                return _honeypot_response()
            _require_module(makerspace, "request_workflow")
        else:
            _require_module(makerspace, "request_workflow")
            if module_enabled(makerspace, "membership"):
                require_active_member_presence(request.user, makerspace)
            else:
                # Waiver acceptance lives on MakerspaceMembership and cannot be recorded
                # with membership off. In this configuration the flow is public request ->
                # STAFF ACCEPT, and staff acceptance is the proposal-time control.
                require_active_account(request.user, makerspace)
            if _honeypot_filled(request.data):
                return _honeypot_response()

        serializer = RequestSubmitSerializer(
            data=request.data,
            context={
                "anonymous_submission": anonymous_submission,
                "checkin_submission": checkin_submission,
            },
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        data.pop("website", None)

        idempotency_key_fingerprint = ""
        payload_fingerprint = ""
        checkin_mid = None
        if checkin_submission:
            checkin_mid = checkin_submit.require_mid(data)
            checkin_submit.charge_mid_throttle(
                request, self, makerspace, checkin_mid, _enforce_throttles
            )
            idempotency_key_fingerprint = _idempotency_fingerprint(request)
            payload_fingerprint = checkin_submit.payload_fingerprint(data, checkin_mid)
            replay = anonymous_idempotency_replay(
                makerspace, idempotency_key_fingerprint, payload_fingerprint
            )
            if replay is not None:
                return Response(
                    RequestSubmitResponseSerializer(replay).data,
                    status=status.HTTP_201_CREATED,
                )
        elif anonymous_submission:
            request.anonymous_contact_email = data["contact_email"]
            _enforce_throttles(request, self, (AnonymousRequestEmailThrottle,))
            idempotency_key_fingerprint = _idempotency_fingerprint(request)
            payload_fingerprint = _anonymous_payload_fingerprint(data)
            replay = anonymous_idempotency_replay(
                makerspace,
                idempotency_key_fingerprint,
                payload_fingerprint,
            )
            if replay is not None:
                return Response(
                    RequestSubmitResponseSerializer(replay).data,
                    status=status.HTTP_201_CREATED,
                )

        product_ids = [item["product_id"] for item in data["items"]]
        products = _requestable_products(product_ids, makerspace)
        if len(products) != len(product_ids):
            raise ValidationError(
                {"items": "One or more products are unavailable for request."}
            )

        if checkin_submission:
            # The only upstream call, and only for a genuinely new request.
            entry, identity = checkin_submit.verify_and_resolve(
                makerspace, mid=checkin_mid, typed_name=data.get("name", ""),
            )
            requester_principal = identity.user
            contact_snapshot = checkin_submit.snapshot(entry, identity)
            audit_actor = identity.user
        elif anonymous_submission:
            requester_principal = get_or_create_anonymous_requester(makerspace)
            contact_snapshot = RequesterSnapshot(
                username="",
                name=data["contact_name"].strip(),
                email=data["contact_email"],
                phone=data.get("contact_phone", ""),
                contact_verified=False,
            )
            audit_actor = None
        else:
            requester_principal = request.user
            contact_snapshot = RequesterSnapshot(
                username=request.user.username,
                name=request.user.display_name,
                email=request.user.email,
                phone=request.user.phone,
                contact_verified=True,
            )
            audit_actor = request.user

        hardware_request = workflow.submit_request(
            makerspace,
            [
                {
                    "product": products[item["product_id"]],
                    "quantity": item["quantity"],
                }
                for item in data["items"]
            ],
            data["requested_for"],
            requester_principal=requester_principal,
            contact_snapshot=contact_snapshot,
            audit_actor=audit_actor,
            idempotency_key_fingerprint=idempotency_key_fingerprint,
            payload_fingerprint=payload_fingerprint,
        )
        return Response(
            RequestSubmitResponseSerializer(hardware_request).data,
            status=status.HTTP_201_CREATED,
        )


class RequestStatusView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "request_status"
    serializer_class = PublicRequestStatusSerializer
    lookup_field = "public_token"

    def get_queryset(self):
        from apps.hardware_requests.view_helpers import request_queryset

        return servable_queryset(request_queryset(), relation="makerspace")

    @extend_schema(
        tags=["Public requests"],
        summary="Get request status by public token",
        auth=[],
        parameters=PUBLIC_API_AUTH_PARAMETERS,
        responses={200: PublicRequestStatusSerializer, 404: ERROR_404},
        examples=[PUBLIC_REQUEST_STATUS_EXAMPLE],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
