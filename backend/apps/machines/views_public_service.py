import uuid
from types import SimpleNamespace

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import MemberPrincipalRateThrottle
from apps.checkin.principal import resolve_request_principal
from apps.hardware_requests import checkin_submit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.public_view_helpers import _enforce_throttles
from apps.machines import service_workflow
from apps.machines.models import Machine, MachineServiceRequest
from apps.machines.public_service_serializers import (
    PublicMachineServiceSubmitResponseSerializer,
    PublicMachineServiceSubmitSerializer,
)
from apps.makerspaces.guards import require_module
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.request_access import checkin_requests_allowed
from apps.presence.guard import require_active_member_presence


SERVICE_SUBMIT_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid machine service request input."),
    401: OpenApiResponse(ErrorSerializer, description="Authentication is required."),
    403: OpenApiResponse(ErrorSerializer, description="Active membership, waiver acceptance, and presence are required."),
    404: OpenApiResponse(ErrorSerializer, description="Makerspace or machine not found."),
    409: OpenApiResponse(ErrorSerializer, description="Machine service request conflict."),
    429: OpenApiResponse(ErrorSerializer, description="Request rate limit exceeded."),
    503: OpenApiResponse(ErrorSerializer, description="Check-in roster is unavailable."),
}


class PublicMachineServiceSubmitView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = "public_request_submit"

    @extend_schema(
        tags=["Public machine service"],
        summary="Submit a public machine service request",
        auth=[{"jwtAuth": []}, {}],
        request=PublicMachineServiceSubmitSerializer,
        responses={201: PublicMachineServiceSubmitResponseSerializer, **SERVICE_SUBMIT_ERRORS},
    )
    def post(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module(makerspace, "machine_service")
        checkin_submission = checkin_requests_allowed(makerspace)
        if not checkin_submission:
            if not request.user.is_authenticated:
                raise NotAuthenticated()
            require_active_member_presence(request.user, makerspace)
        if _honeypot_filled(request.data):
            decoy = SimpleNamespace(
                public_token=uuid.uuid4(), status=MachineServiceRequest.Status.PENDING,
            )
            return Response(
                PublicMachineServiceSubmitResponseSerializer(decoy).data,
                status=status.HTTP_201_CREATED,
            )
        serializer = PublicMachineServiceSubmitSerializer(
            data=request.data,
            context={"checkin_submission": checkin_submission},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if checkin_submission:
            checkin_mid = checkin_submit.require_mid(data)
            checkin_submit.charge_mid_throttle(
                request, self, makerspace, checkin_mid, _enforce_throttles
            )
        else:
            checkin_mid = None
        machine = get_object_or_404(
            Machine.objects.filter(makerspace=makerspace, is_active=True),
            pk=data["machine_id"],
        )
        principal = resolve_request_principal(
            makerspace,
            request,
            mid=checkin_mid,
            typed_name=data.get("name", ""),
        )
        actor = principal.user if principal is not None else request.user
        service_request = service_workflow.submit(
            machine,
            actor,
            member=actor,
            actor=actor,
            requester_name=actor.display_name,
            contact_email=actor.email,
            contact_phone=actor.phone,
            title=data["title"],
            description=data.get("description", ""),
            source_link=data.get("source_link", ""),
            capability_payload=data.get("capability_payload"),
        )
        return Response(
            PublicMachineServiceSubmitResponseSerializer(service_request).data,
            status=status.HTTP_201_CREATED,
        )


def _honeypot_filled(payload):
    try:
        value = payload.get("website", "")
    except AttributeError:
        return False
    return bool(str(value).strip())
