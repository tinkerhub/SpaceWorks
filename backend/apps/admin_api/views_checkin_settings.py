"""A makerspace's own check-in roster settings, and a button to test them.

Reading is open to the makerspace's staff (the card renders read-only for them);
writing and testing need `manage_makerspace` there, or superadmin. Testing is a
server-side fetch of a URL the caller chooses, so it is held to the same permission
as saving one, and it goes through the same outbound SSRF guard.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_checkin_settings import (
    CheckinSettingsErrorSerializer,
    CheckinSettingsSerializer,
    CheckinSettingsUpdateSerializer,
    CheckinTestRequestSerializer,
    CheckinTestResultSerializer,
)
from apps.checkin import settings_service
from apps.makerspaces.servability import servable_queryset

_ERRORS = {
    403: OpenApiResponse(
        response=CheckinSettingsErrorSerializer,
        description="Not signed in as active staff, or outside this origin's makerspace.",
    ),
    404: OpenApiResponse(
        response=CheckinSettingsErrorSerializer,
        description="Makerspace not found, or you lack the required action there.",
    ),
}


def _makerspace(request, makerspace_id, action):
    return get_object_or_404(
        rbac.scope_by_action(request.user, action, servable_queryset(), field="id"),
        pk=makerspace_id,
    )


class CheckinSettingsView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Retrieve this makerspace's check-in settings",
        responses={200: CheckinSettingsSerializer, **_ERRORS},
    )
    def get(self, request, makerspace_id):
        makerspace = _makerspace(request, makerspace_id, rbac.Action.VIEW_INVENTORY)
        return Response(settings_service.settings_payload(makerspace))

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Update this makerspace's check-in settings",
        description=(
            "Blank roster fields fall back to the deployment settings. "
            "`public_request_mode` is applied through the same writer as "
            "`manage.py set_request_access`, so membership still wins."
        ),
        request=CheckinSettingsUpdateSerializer,
        responses={
            200: CheckinSettingsSerializer,
            400: OpenApiResponse(
                description=(
                    "Invalid field, a roster URL refused by the outbound guard, or a mode "
                    "this makerspace cannot serve (membership installed, no roster, no "
                    "space ID)."
                ),
            ),
            **_ERRORS,
        },
    )
    def patch(self, request, makerspace_id):
        makerspace = _makerspace(request, makerspace_id, rbac.Action.MANAGE_MAKERSPACE)
        # Validated before any lock: the URL check resolves DNS.
        serializer = CheckinSettingsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = settings_service.update_settings(
            makerspace, serializer.validated_data, actor=request.user
        )
        return Response(settings_service.settings_payload(updated))


class CheckinSettingsTestView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Test reading the check-in roster",
        description=(
            "Fetches the roster once, uncached, from the candidate URL or the saved one. "
            "A failure is an expected diagnostic outcome: `ok: false` with a readable "
            "`reason`. The upstream body is never echoed."
        ),
        request=CheckinTestRequestSerializer,
        responses={
            200: CheckinTestResultSerializer,
            400: OpenApiResponse(description="Malformed request body."),
            **_ERRORS,
        },
    )
    def post(self, request, makerspace_id):
        makerspace = _makerspace(request, makerspace_id, rbac.Action.MANAGE_MAKERSPACE)
        serializer = CheckinTestRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidate = serializer.validated_data.get("checkin_api_url", "")
        return Response(settings_service.test_connection(makerspace, candidate))
