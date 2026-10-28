from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_roles import (
    MemberMachineScopeSerializer,
    MemberMachineScopeWriteSerializer,
)
from apps.admin_api.views_roles import ERRORS, _makerspace
from apps.machines import member_scope_services
from apps.makerspaces.models import MakerspaceMembership


def _membership(makerspace, membership_id):
    return get_object_or_404(
        MakerspaceMembership.objects.select_related("assigned_role", "user"),
        pk=membership_id,
        makerspace=makerspace,
    )


class MemberMachineScopeView(APIView):
    """Machine types one member manages on top of their role's links.

    Space-manager only (`_makerspace` requires MANAGE_MAKERSPACE, and the service
    revalidates it under locks). Personal links only widen a MANAGE_MACHINES grant the
    member's role already holds; they never grant it.
    """

    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin memberships"], responses={200: MemberMachineScopeSerializer, **ERRORS})
    def get(self, request, makerspace_id, membership_id):
        makerspace = _makerspace(request.user, makerspace_id)
        membership = _membership(makerspace, membership_id)
        payload = member_scope_services.member_scope_payload(makerspace, membership)
        return Response(MemberMachineScopeSerializer(payload).data)

    @extend_schema(
        tags=["Admin memberships"],
        request=MemberMachineScopeWriteSerializer,
        responses={200: MemberMachineScopeSerializer, **ERRORS},
    )
    def put(self, request, makerspace_id, membership_id):
        makerspace = _makerspace(request.user, makerspace_id)
        membership = _membership(makerspace, membership_id)
        serializer = MemberMachineScopeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member_scope_services.set_member_machine_scope(
            makerspace=makerspace,
            membership=membership,
            actor=request.user,
            **serializer.validated_data,
        )
        membership = _membership(makerspace, membership_id)
        payload = member_scope_services.member_scope_payload(makerspace, membership)
        return Response(MemberMachineScopeSerializer(payload).data)
