"""Staff-only setup, with identical read/write authority and no public GET writes."""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.machines.service_public_queue import enable_public_queue, public_queue_state
from apps.makerspaces.models import Makerspace


class PublicPrinterQueueStateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    queue_id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField(allow_null=True)


class PublicPrinterQueueErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField(required=False)


class PublicPrinterQueueEnableSerializer(serializers.Serializer):
    """Empty body: setup preserves all existing queue configuration."""

    def validate(self, attrs):
        if self.initial_data:
            raise serializers.ValidationError("Send an empty object; queue configuration is preserved.")
        return attrs


_RESPONSES = {
    200: PublicPrinterQueueStateSerializer,
    400: OpenApiResponse({"type": "object", "additionalProperties": {}}, description="A required module is disabled, the built-in printer type is missing, or the body is invalid."),
    401: OpenApiResponse(PublicPrinterQueueErrorSerializer, description="Authentication required."),
    403: OpenApiResponse(PublicPrinterQueueErrorSerializer, description="Active staff with MANAGE_MACHINES and full built-in printer type scope required."),
    404: OpenApiResponse(PublicPrinterQueueErrorSerializer, description="Makerspace is absent or outside the actor's scope."),
    409: OpenApiResponse(PublicPrinterQueueErrorSerializer, description="Public Requests belongs to another machine type; no queue is changed."),
}


class MachinePrinterQueueView(APIView):
    permission_classes = [IsActiveStaff]

    def _space(self, actor, makerspace_id):
        return get_object_or_404(
            rbac.scope_by_makerspace(actor, Makerspace.objects.all(), makerspace_field="id"),
            pk=makerspace_id,
        )

    @extend_schema(
        tags=["Admin machine service"], summary="Read public printer queue setup",
        description="Requires machines, machine_service and printing, plus full built-in printer type management scope. Does not create or activate queues.",
        request=None, responses=_RESPONSES,
    )
    def get(self, request, makerspace_id):
        return Response(public_queue_state(request.user, self._space(request.user, makerspace_id)))

    @extend_schema(
        tags=["Admin machine service"], summary="Enable public print requests",
        description="Idempotently reuses an active built-in printer queue, or activates/creates only Public Requests. Authority and module gates are rechecked under the makerspace lock; only actual changes are audited.",
        request={"application/json": {"type": "object", "additionalProperties": False}}, responses=_RESPONSES,
    )
    def post(self, request, makerspace_id):
        space = self._space(request.user, makerspace_id)
        data = PublicPrinterQueueEnableSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(enable_public_queue(request.user, space))
