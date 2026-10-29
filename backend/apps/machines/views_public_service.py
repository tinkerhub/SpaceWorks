import uuid
from types import SimpleNamespace

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import MemberPrincipalRateThrottle
from apps.checkin.principal import resolve_request_principal
from apps.hardware_requests import checkin_submit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.public_view_helpers import _enforce_throttles
from apps.machines.printer_capabilities import is_printer_type
from apps.machines.public_service_catalog import resolve_public_service_type
from apps.machines.public_service_intake import submit_typed_request
from apps.machines.public_service_legacy import submit_legacy_machine
from apps.machines.models import Machine, MachineServiceRequest
from apps.machines.public_service_serializers import (
    PublicMachineServiceSubmitResponseSerializer,
    PublicMachineServiceSubmitSerializer, PRINTER_INPUT_FIELDS,
)
from apps.makerspaces.guards import require_module
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.request_access import checkin_requests_allowed
from apps.presence.guard import require_active_account, require_active_member_presence
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS


SERVICE_SUBMIT_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid machine service request input."),
    401: OpenApiResponse(ErrorSerializer, description="Authentication is required."),
    403: OpenApiResponse(ErrorSerializer, description="Active membership, waiver acceptance, and presence are required."),
    404: OpenApiResponse(ErrorSerializer, description="Makerspace, published machine type or machine not found."),
    409: OpenApiResponse(ErrorSerializer, description="Machine service request conflict."),
    429: OpenApiResponse(ErrorSerializer, description="Request rate limit exceeded."),
    503: OpenApiResponse(ErrorSerializer, description="Check-in roster, storage or protected writes are temporarily unavailable."),
}


def require_public_machine_requester(user, makerspace):
    """Same identity contract as the public BORROW request, for the same reason.

    A machine-service or print request is a PROPOSAL that staff act on -- the requester is
    asking for a job to be run, not operating the machine themselves -- so it must not
    hard-require a MakerspaceMembership row. Doing so made the surface dead for every
    ordinary account on the default `recommended` profile, which ships `machine_service`
    with `membership` off.

    Mirrors `apps/hardware_requests/public_views.py`: membership, waiver and presence when
    the community module is installed; an active account when it is not, because waiver
    acceptance lives on MakerspaceMembership and cannot be recorded at all without it.
    """
    if module_enabled(makerspace, "membership"):
        return require_active_member_presence(user, makerspace)
    return require_active_account(user, makerspace)

class PublicMachineServiceSubmitView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = "public_request_submit"

    @extend_schema(
        tags=["Public machine service"],
        summary="Submit a public machine service request",
        description="Choose machine_type_id for an unassigned queued proposal; staff assign the machine later. Supply exactly one of machine_type_id or the legacy machine_id. Printer fields are accepted only for printer types. Requires an active requester or a verified checked-in principal.",
        parameters=PUBLIC_API_AUTH_PARAMETERS,
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
            # main's helper, not require_active_member_presence directly: a service
            # request is a PROPOSAL staff act on, so it must not hard-require a
            # membership row on profiles that ship machine_service with membership off.
            require_public_machine_requester(request.user, makerspace)
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
        if "machine_type_id" in data:
            machine_type = resolve_public_service_type(makerspace, data["machine_type_id"])
            if not is_printer_type(machine_type) and PRINTER_INPUT_FIELDS.intersection(request.data):
                raise ValidationError("Printer fields require a printer machine type.")
        else:
            machine = get_object_or_404(
                Machine.objects.select_related("machine_type").filter(makerspace=makerspace, is_active=True),
                pk=data["machine_id"],
            )
            if is_printer_type(machine.machine_type):
                require_module(makerspace, "printing")
        principal = resolve_request_principal(
            makerspace,
            request,
            mid=checkin_mid,
            typed_name=data.get("name", ""),
        )
        actor = principal.user if principal is not None else request.user
        if "machine_type_id" in data:
            service_request = submit_typed_request(
                makerspace, data, actor,
                supplied_printer_fields=PRINTER_INPUT_FIELDS.intersection(request.data),
            )
        else:
            service_request = submit_legacy_machine(makerspace, data["machine_id"], data, actor)
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
