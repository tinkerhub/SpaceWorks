"""Private hardware-request history using the public status field allowlist."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.accounts.request_history import (
    RequestHistoryErrorSerializer, RequestHistoryModuleErrorSerializer,
    RequestHistoryPagination, require_history_account,
)
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.serializers_public import PublicRequestStatusSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.lookup import get_public_makerspace
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS


class OwnRequestStatusSerializer(PublicRequestStatusSerializer):
    public_token = serializers.UUIDField(read_only=True)


@extend_schema(
    tags=["Public requests"],
    summary="List my hardware requests in this makerspace",
    description=(
        "Requires an active personal account. Returns only requests owned by the "
        "signed-in account, newest first; community membership and current check-in "
        "are not required. Uses pages of 24 and the public status field allowlist."
    ),
    auth=[{"jwtAuth": []}],
    parameters=PUBLIC_API_AUTH_PARAMETERS,
    responses={
        200: OwnRequestStatusSerializer(many=True),
        400: OpenApiResponse(RequestHistoryModuleErrorSerializer, description="Request workflow module disabled."),
        401: OpenApiResponse(RequestHistoryErrorSerializer, description="Authentication required."),
        403: OpenApiResponse(RequestHistoryErrorSerializer, description="Account or site scope refused."),
        404: OpenApiResponse(RequestHistoryErrorSerializer, description="Makerspace or page not found."),
    },
)
class OwnRequestsView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OwnRequestStatusSerializer
    pagination_class = RequestHistoryPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return HardwareRequest.objects.none()
        makerspace = get_public_makerspace(self.kwargs["makerspace_slug"])
        require_history_account(self.request, self, makerspace)
        require_module(makerspace, "request_workflow")
        return HardwareRequest.objects.filter(
            makerspace=makerspace, requester=self.request.user,
        ).prefetch_related("items__product").order_by("-created_at", "-id")
