"""Public type catalog, owned staging and token tracking for any machine type."""
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.checkin.principal import resolve_request_principal
from apps.checkin.throttles import CheckinMidUploadThrottle
from apps.hardware_requests import checkin_submit
from apps.hardware_requests.public_view_helpers import _enforce_throttles
from apps.machines.models import MachineType
from apps.machines.public_service_catalog import public_service_types, resolve_public_service_type
from apps.machines.public_service_intake import public_service_status, stage_typed_upload, validate_type_upload
from apps.machines.public_service_serializers import (
    PublicMachineServiceStatusSerializer, PublicMachineServiceTypeSerializer,
    PublicMachineServiceUploadResponseSerializer, PublicMachineServiceUploadSerializer,
)
from apps.machines.views_public_service import SERVICE_SUBMIT_ERRORS, require_public_machine_requester
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.request_access import checkin_requests_allowed
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS


@extend_schema(
    tags=["Public machine service"], summary="List published machine service types",
    description="Published active machines in idle, running or reserved state accept queued proposals. This read never initializes a queue.",
    auth=[], parameters=PUBLIC_API_AUTH_PARAMETERS,
    responses={200: PublicMachineServiceTypeSerializer(many=True), **SERVICE_SUBMIT_ERRORS},
)
class PublicMachineServiceTypesView(ListAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"
    serializer_class = PublicMachineServiceTypeSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MachineType.objects.none()
        self.makerspace = get_public_makerspace(self.kwargs["makerspace_slug"])
        return public_service_types(self.makerspace)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "makerspace": getattr(self, "makerspace", None)}


class PublicMachineServiceUploadView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "print_request_submit"

    @extend_schema(
        tags=["Public machine service"], summary="Stage an owned machine-type attachment",
        description="Requires an active requester, membership/presence when installed, or a verified checked-in principal. Returns the exact queue pin for submission; upload bytes to the returned presign before submitting.",
        auth=[{"jwtAuth": []}, {}], parameters=PUBLIC_API_AUTH_PARAMETERS,
        request=PublicMachineServiceUploadSerializer,
        responses={201: PublicMachineServiceUploadResponseSerializer, **SERVICE_SUBMIT_ERRORS},
    )
    def post(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        checked_in = checkin_requests_allowed(makerspace)
        if not checked_in:
            if not request.user.is_authenticated:
                raise NotAuthenticated()
            require_public_machine_requester(request.user, makerspace)
        serializer = PublicMachineServiceUploadSerializer(
            data=request.data, context={"checkin_submission": checked_in},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        machine_type = resolve_public_service_type(makerspace, data["machine_type_id"])
        validate_type_upload(machine_type, data)
        mid = None
        if checked_in:
            mid = checkin_submit.require_mid(data)
            checkin_submit.charge_mid_throttle(
                request, self, makerspace, mid, _enforce_throttles,
                throttles=(CheckinMidUploadThrottle,),
            )
        principal = resolve_request_principal(makerspace, request, mid=mid, typed_name=data.get("name", ""))
        actor = principal.user if principal is not None else request.user
        return Response(stage_typed_upload(makerspace, data, actor), status=status.HTTP_201_CREATED)


class PublicMachineServiceStatusView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "request_status"

    @extend_schema(
        tags=["Public machine service"], summary="Track machine service by public token",
        description="PII-free lifecycle and queue position. A disabled service module returns the same response as an unknown token.",
        auth=[], parameters=PUBLIC_API_AUTH_PARAMETERS,
        responses={200: PublicMachineServiceStatusSerializer, **SERVICE_SUBMIT_ERRORS},
    )
    def get(self, request, public_token):
        row, counts = public_service_status(public_token)
        return Response(PublicMachineServiceStatusSerializer(row, context={"queue_counts": counts}).data)
