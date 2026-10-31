"""Account-owned service history; legacy staff requester attribution is not ownership."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.accounts.request_history import (
    RequestHistoryErrorSerializer, RequestHistoryModuleErrorSerializer,
    RequestHistoryPagination, require_history_account,
)
from apps.machines.models import MachineServiceRequest
from apps.machines.public_service_serializers import PublicMachineServiceStatusSerializer
from apps.machines.service_queue_position import queue_counts_for
from apps.makerspaces.guards import require_module
from apps.makerspaces.lookup import get_public_makerspace
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS


@extend_schema(
    tags=["Public machine service"],
    summary="List my machine service requests in this makerspace",
    description=(
        "Requires an active personal account. Returns only requests whose member "
        "is the signed-in account, newest first, in pages of 24. Community membership "
        "and current check-in are not required. Uses the public status field allowlist."
    ),
    auth=[{"jwtAuth": []}],
    parameters=PUBLIC_API_AUTH_PARAMETERS,
    responses={
        200: PublicMachineServiceStatusSerializer(many=True),
        400: OpenApiResponse(RequestHistoryModuleErrorSerializer, description="Machine service module disabled."),
        401: OpenApiResponse(RequestHistoryErrorSerializer, description="Authentication required."),
        403: OpenApiResponse(RequestHistoryErrorSerializer, description="Account or site scope refused."),
        404: OpenApiResponse(RequestHistoryErrorSerializer, description="Makerspace or page not found."),
    },
)
class OwnMachineServiceRequestsView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PublicMachineServiceStatusSerializer
    pagination_class = RequestHistoryPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MachineServiceRequest.objects.none()
        makerspace = get_public_makerspace(self.kwargs["makerspace_slug"])
        require_history_account(self.request, self, makerspace)
        require_module(makerspace, "machine_service")
        return MachineServiceRequest.objects.filter(
            makerspace=makerspace, member=self.request.user,
        ).order_by("-created_at", "-id")

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        self.queue_counts = queue_counts_for(page) if page is not None else {}
        return page

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            "queue_counts": getattr(self, "queue_counts", {}),
        }
