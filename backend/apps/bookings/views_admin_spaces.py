from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.bookings.serializers_admin import (
    BookableSpaceAdminSerializer,
    BookableSpaceListResponseSerializer,
    BookableSpaceWriteSerializer,
    EmptyActionSerializer,
    SpaceImageFinalizeRequestSerializer,
    SpaceImagePresignRequestSerializer,
    SpaceImagePresignResponseSerializer,
)
from apps.bookings import services, services_images, storage
from apps.bookings.models import BookableSpace
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.hardware_requests.view_helpers import (
    ERROR_400,
    ERROR_403,
    ERROR_404,
    ERROR_409,
    ERROR_503,
)
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace


from apps.bookings.views_space_common import (
    SCOPED_ERROR_RESPONSES, VALIDATED_ERROR_RESPONSES, IMAGE_ERROR_RESPONSES,
    manageable_space, _require_active,
)


class _SpacePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def _visible_makerspace(actor, makerspace_id):
    makerspace = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_BOOKINGS,
            Makerspace.objects.all(),
            field='id',
        ),
        pk=makerspace_id,
    )
    require_module(makerspace, 'bookings')
    if not rbac.can(actor, rbac.Action.MANAGE_BOOKINGS, makerspace.pk):
        raise PermissionDenied()
    return makerspace




def _page_response(paginator, page, serializer):
    return Response(
        {
            'count': paginator.page.paginator.count,
            'next': paginator.get_next_link(),
            'previous': paginator.get_previous_link(),
            'results': serializer(page, many=True).data,
        }
    )




class BookableSpaceListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='List bookable spaces in a makerspace',
        request=None,
        responses={200: BookableSpaceListResponseSerializer, **SCOPED_ERROR_RESPONSES},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _visible_makerspace(request.user, makerspace_id)
        queryset = rbac.scope_by_action(
            request.user,
            rbac.Action.MANAGE_BOOKINGS,
            BookableSpace.objects.select_related('makerspace').filter(
                makerspace=makerspace
            ),
            field='makerspace_id',
        ).order_by('name', 'id')
        paginator = _SpacePagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return _page_response(paginator, page, BookableSpaceAdminSerializer)

    @extend_schema(
        tags=['Admin bookings'],
        summary='Create a bookable space',
        request=BookableSpaceWriteSerializer,
        responses={201: BookableSpaceAdminSerializer, **VALIDATED_ERROR_RESPONSES},
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = _visible_makerspace(request.user, makerspace_id)
        serializer = BookableSpaceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        space = services.create_space(
            makerspace=makerspace,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            BookableSpaceAdminSerializer(space).data,
            status=status.HTTP_201_CREATED,
        )


class BookableSpaceDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Retrieve a bookable space',
        request=None,
        responses={200: BookableSpaceAdminSerializer, **SCOPED_ERROR_RESPONSES},
    )
    def get(self, request, pk, *args, **kwargs):
        return Response(
            BookableSpaceAdminSerializer(manageable_space(request.user, pk)).data
        )

    @extend_schema(
        tags=['Admin bookings'],
        summary='Update a bookable space',
        request=BookableSpaceWriteSerializer,
        responses={
            200: BookableSpaceAdminSerializer,
            **VALIDATED_ERROR_RESPONSES,
            409: ERROR_409,
        },
    )
    def patch(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        serializer = BookableSpaceWriteSerializer(
            space,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        space = services.update_space(
            space,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(BookableSpaceAdminSerializer(space).data)


class BookableSpaceDeactivateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Deactivate a bookable space',
        request=EmptyActionSerializer,
        responses={
            200: BookableSpaceAdminSerializer,
            **VALIDATED_ERROR_RESPONSES,
            409: ERROR_409,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        serializer = EmptyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        space = services.deactivate_space(space, actor=request.user)
        return Response(BookableSpaceAdminSerializer(space).data)


# Explicit compatibility exports; image handlers live in their focused module.
from apps.bookings.views_space_images import (
    BookableSpaceImagePresignView, BookableSpaceImageFinalizeView,
    BookableSpaceImageDeleteView,
)
