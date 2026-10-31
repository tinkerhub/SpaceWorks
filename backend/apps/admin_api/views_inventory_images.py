from apps.object_storage_lifecycle import storage_lifecycle
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.admin_api.serializers_inventory import (
    InventoryProductAdminSerializer,
    PublicImageAttachRequestSerializer,
    PublicImageUploadRequestSerializer,
    PublicImageUploadResponseSerializer,
)
from apps.audit import services as audit
from apps.inventory import public_image_storage
from apps.inventory.public_image_attach import PublicImageRejected, finalize_product_image
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.inventory.models import InventoryProduct
from apps.makerspaces.guards import require_module
from apps.makerspaces.limits import add_storage


class InventoryProductImageView(APIView):
    permission_classes = [IsActiveStaff]

    def _product(self, request, pk):
        product = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.VIEW_INVENTORY,
                InventoryProduct.objects.select_related("makerspace"),
            ),
            pk=pk,
        )
        require_module(product.makerspace_id, "staff_admin")
        require_action(request.user, rbac.Action.EDIT_INVENTORY, product.makerspace_id)
        return product

    @extend_schema(
        tags=["Admin inventory"],
        summary="Create an inventory product image upload URL",
        request=PublicImageUploadRequestSerializer,
        responses={
            201: PublicImageUploadResponseSerializer,
            400: OpenApiResponse(description="Invalid image upload request."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        product = self._product(request, pk)
        serializer = PublicImageUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]
        ext = public_image_storage.ext_for(
            content_type,
            serializer.validated_data["filename"],
        )
        object_key = public_image_storage.build_object_key(
            "items",
            product.makerspace_id,
            ext,
        )
        try:
            upload = public_image_storage.presigned_upload(object_key, content_type)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(
            PublicImageUploadResponseSerializer({"object_key": object_key, **upload}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["Admin inventory"],
        summary="Attach an uploaded image to an inventory product",
        request=PublicImageAttachRequestSerializer,
        responses={
            200: InventoryProductAdminSerializer,
            400: OpenApiResponse(description="Invalid image object key or size."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    def put(self, request, pk, *args, **kwargs):
        product = self._product(request, pk)
        with storage_lifecycle(product.makerspace_id) as guard:
            serializer = PublicImageAttachRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            object_key = serializer.validated_data["object_key"]
            try:
                size = finalize_product_image(
                    product.makerspace_id, object_key, product_id=product.pk
                )
            except PublicImageRejected as exc:
                raise ValidationError({"object_key": str(exc)}) from exc
            except StorageUnavailable:
                return storage_unavailable_response()
            guard.verify()
            with transaction.atomic():
                product = self._product(request, pk)
                product = InventoryProduct.objects.select_for_update().select_related(
                    "makerspace"
                ).get(pk=product.pk)
                guard.verify(product.makerspace_id)
                if object_key and public_image_storage.public_image_key_in_use(
                    product.makerspace_id,
                    object_key,
                    product_id=product.pk,
                ):
                    raise ValidationError({"object_key": "This image is already in use."})
                old_key = product.image_key
                if object_key != old_key:
                    add_storage(product.makerspace, size)
                if old_key and old_key != object_key:
                    public_image_storage.release_public_image_on_commit(
                        product.makerspace, old_key, guard=guard
                    )
                product.image_key = object_key
                product.save(update_fields=["image_key", "updated_at"])
                audit.record(
                    request.user,
                    "inventory.image_attached",
                    makerspace=product.makerspace,
                    target=product,
                )
                return Response(InventoryProductAdminSerializer(product).data)

    @extend_schema(
        tags=["Admin inventory"],
        summary="Clear an inventory product image",
        responses={
            200: InventoryProductAdminSerializer,
        },
    )
    def delete(self, request, pk, *args, **kwargs):
        product = self._product(request, pk)
        with storage_lifecycle(product.makerspace_id) as guard:
            guard.verify()
            with transaction.atomic():
                product = self._product(request, pk)
                product = InventoryProduct.objects.select_for_update().select_related(
                    "makerspace"
                ).get(pk=product.pk)
                guard.verify(product.makerspace_id)
                old_key = product.image_key
                if old_key:
                    public_image_storage.release_public_image_on_commit(
                        product.makerspace, old_key, guard=guard
                    )
                product.image_key = ""
                product.save(update_fields=["image_key", "updated_at"])
                audit.record(
                    request.user,
                    "inventory.image_cleared",
                    makerspace=product.makerspace,
                    target=product,
                )
                return Response(InventoryProductAdminSerializer(product).data)
