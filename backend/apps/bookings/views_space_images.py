from apps.object_storage_lifecycle import storage_lifecycle
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


from apps.bookings.views_space_common import manageable_space, _require_active, IMAGE_ERROR_RESPONSES


class BookableSpaceImagePresignView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Create a space image upload URL',
        request=SpaceImagePresignRequestSerializer,
        responses={201: SpaceImagePresignResponseSerializer, **IMAGE_ERROR_RESPONSES},
    )
    def post(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        _require_active(space)
        serializer = SpaceImagePresignRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data['content_type']
        ext = storage.ext_for(content_type, serializer.validated_data['filename'])
        object_key = storage.build_object_key(space.makerspace_id, space.pk, ext)
        try:
            upload = storage.presigned_upload(object_key, content_type)
        except StorageUnavailable:
            return storage_unavailable_response()
        data = {'object_key': object_key, 'upload': upload}
        return Response(
            SpaceImagePresignResponseSerializer(data).data,
            status=status.HTTP_201_CREATED,
        )


def _cleanup_new_upload(space, object_key):
    services_images.cleanup_unattached_space_image(
        space,
        object_key=object_key,
        storage=storage,
    )


class BookableSpaceImageFinalizeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Finalize and attach a space image',
        request=SpaceImageFinalizeRequestSerializer,
        responses={200: BookableSpaceAdminSerializer, **IMAGE_ERROR_RESPONSES},
    )
    def post(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        with storage_lifecycle(space.makerspace_id) as guard:
            _require_active(space)
            serializer = SpaceImageFinalizeRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            object_key = serializer.validated_data['object_key']
            services.validate_space_image_key(space, object_key)
            if object_key != space.image_key and storage.public_image_key_in_use(space.makerspace_id, object_key, space_id=space.pk):
                raise ValidationError({'object_key': 'This image is already in use.'})
            try:
                result = storage.finalize_upload(object_key)
            except StorageUnavailable:
                _cleanup_new_upload(space, object_key)
                return storage_unavailable_response()
            if result.status != 'ok':
                _cleanup_new_upload(space, object_key)
                raise ValidationError(
                    {'object_key': storage.finalize_error_message(result)}
                )
            try:
                space = services.set_space_image(
                    space,
                    actor=request.user,
                    object_key=object_key,
                    size_bytes=result.size,
                    guard=guard,
                )
            except Exception:
                _cleanup_new_upload(space, object_key)
                raise
            return Response(BookableSpaceAdminSerializer(space).data)


class BookableSpaceImageDeleteView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Delete a space image',
        request=None,
        responses={204: None, **IMAGE_ERROR_RESPONSES},
    )
    def delete(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        with storage_lifecycle(space.makerspace_id) as guard:
            services.remove_space_image(space, actor=request.user, guard=guard)
            return Response(status=status.HTTP_204_NO_CONTENT)
