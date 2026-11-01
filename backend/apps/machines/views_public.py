from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.machines.models import Machine
from apps.machines.serializers_public_machines import PublicMachineSerializer
from apps.machines.usage_totals import annotate_machine_usage
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import module_enabled
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS


@extend_schema(
    tags=['Public machines'],
    summary='List public machines',
    description='List active machines published by a public makerspace.',
    parameters=[
        *PUBLIC_API_AUTH_PARAMETERS,
        OpenApiParameter(
            name='makerspace_slug',
            type=str,
            location=OpenApiParameter.PATH,
            description='Public makerspace code or slug.',
        ),
    ],
    responses=PublicMachineSerializer(many=True),
)
class PublicMachineListView(ListAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = 'public_read'
    serializer_class = PublicMachineSerializer

    def get_queryset(self):
        makerspace = get_public_makerspace(self.kwargs['makerspace_slug'])
        if not makerspace.public_inventory_enabled or not module_enabled(
            makerspace, 'machines'
        ):
            raise Http404
        return annotate_machine_usage(
            Machine.objects.select_related('machine_type')
            .filter(
                makerspace=makerspace,
                is_public=True,
                is_active=True,
            )
            .order_by('name', 'id')
        )
