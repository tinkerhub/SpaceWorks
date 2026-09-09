from types import SimpleNamespace
import uuid

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.checkin.principal import resolve_request_principal
from apps.checkin.throttles import CheckinMidUploadThrottle
from apps.hardware_requests import checkin_submit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.public_view_helpers import _enforce_throttles
from apps.machines.models import MachineServiceRequest
from apps.machines.public_printer_service import public_pools, public_queues, public_status, resolve_queue, stage_upload, submit_request
from apps.machines.public_printer_service_serializers import PublicPrinterPoolSerializer, PublicPrinterQueueSerializer, PublicPrinterStatusSerializer, PublicPrinterSubmitResponseSerializer, PublicPrinterSubmitSerializer, PublicPrinterUploadSerializer
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.request_access import checkin_requests_allowed
from apps.presence.guard import require_active_member_presence


def _require_printer_module(makerspace):
    if not module_enabled(makerspace, "machine_service"):
        from rest_framework.exceptions import ValidationError
        raise ValidationError({"module": "machine service is disabled for this makerspace."})


class PublicPrinterQueuesView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(tags=["Public machine service"], auth=[], responses={200: PublicPrinterQueueSerializer(many=True)})
    def get(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        _require_printer_module(makerspace)
        return Response(PublicPrinterQueueSerializer(public_queues(makerspace), many=True).data)


class PublicPrinterPoolsView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(tags=["Public machine service"], auth=[], responses={200: PublicPrinterPoolSerializer(many=True)})
    def get(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        _require_printer_module(makerspace)
        return Response(PublicPrinterPoolSerializer(public_pools(makerspace), many=True).data)


class PublicPrinterUploadView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "print_request_submit"

    @extend_schema(
        tags=["Public machine service"],
        auth=[{"jwtAuth": []}, {}],
        request=PublicPrinterUploadSerializer,
        responses={
            201: PublicPrinterSubmitResponseSerializer,
            503: OpenApiResponse(
                ErrorSerializer, description="Check-in roster is unavailable."
            ),
        },
    )
    def post(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        _require_printer_module(makerspace)
        checkin_submission = checkin_requests_allowed(makerspace)
        if not checkin_submission:
            if not request.user.is_authenticated:
                raise NotAuthenticated()
            require_active_member_presence(request.user, makerspace)
        serializer = PublicPrinterUploadSerializer(
            data=request.data,
            context={"checkin_submission": checkin_submission},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if checkin_submission:
            checkin_mid = checkin_submit.require_mid(data)
            checkin_submit.charge_mid_throttle(
                request,
                self,
                makerspace,
                checkin_mid,
                _enforce_throttles,
                throttles=(CheckinMidUploadThrottle,),
            )
            resolve_queue(makerspace, data.get("queue_id"))
        else:
            checkin_mid = None
        principal = resolve_request_principal(
            makerspace,
            request,
            mid=checkin_mid,
            typed_name=data.get("name", ""),
        )
        actor = principal.user if principal is not None else request.user
        return Response(stage_upload(makerspace, data, actor), status=status.HTTP_201_CREATED)


class PublicPrinterRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "print_request_submit"

    @extend_schema(
        tags=["Public machine service"],
        auth=[{"jwtAuth": []}, {}],
        request=PublicPrinterSubmitSerializer,
        responses={
            201: PublicPrinterSubmitResponseSerializer,
            503: OpenApiResponse(
                ErrorSerializer, description="Check-in roster is unavailable."
            ),
        },
    )
    def post(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        _require_printer_module(makerspace)
        checkin_submission = checkin_requests_allowed(makerspace)
        if not checkin_submission and not request.user.is_authenticated:
            raise NotAuthenticated()
        if str(request.data.get("website", "")).strip():
            decoy = SimpleNamespace(public_token=uuid.uuid4(), status=MachineServiceRequest.Status.PENDING)
            return Response(PublicPrinterSubmitResponseSerializer(decoy).data, status=status.HTTP_201_CREATED)
        if not checkin_submission:
            require_active_member_presence(request.user, makerspace)
        serializer = PublicPrinterSubmitSerializer(
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
            resolve_queue(makerspace, data.get("queue_id"))
        else:
            checkin_mid = None
        principal = resolve_request_principal(
            makerspace,
            request,
            mid=checkin_mid,
            typed_name=data.get("name", ""),
        )
        actor = principal.user if principal is not None else request.user
        row = submit_request(makerspace, data, actor)
        return Response(PublicPrinterSubmitResponseSerializer(row).data, status=status.HTTP_201_CREATED)


class PublicPrinterStatusView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "request_status"

    @extend_schema(tags=["Public machine service"], auth=[], responses={200: PublicPrinterStatusSerializer})
    def get(self, request, public_token):
        row, counts = public_status(public_token)
        return Response(PublicPrinterStatusSerializer(row, context={"queue_counts": counts}).data)
