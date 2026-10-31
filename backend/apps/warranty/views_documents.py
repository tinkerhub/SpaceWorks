from django.db import transaction
from apps.object_storage_lifecycle import storage_lifecycle
from apps.object_storage_references import private_key_in_use
from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.warranty.serializers import (
    WarrantyDocumentFinalizeSerializer,
    WarrantyDocumentPresignSerializer,
    WarrantyDocumentSerializer,
    WarrantyDocumentUploadResponseSerializer,
    WarrantyDocumentUrlSerializer,
)
from apps.warranty.access import enforce, resolve_document, resolve_warranty
from apps.audit import services as audit
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.makerspaces import limits
from apps.document_storage_charge import DocumentChargeProofUnavailable
from apps.document_storage_quota import charge_metadata
from apps.makerspaces.guards import require_module_locked
from apps.warranty import storage
from apps.warranty.models import Warranty, WarrantyDocument


ERRORS = {401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer}


class WarrantyDocumentPresignView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin warranty"],
        summary="Create a warranty document upload URL",
        request=WarrantyDocumentPresignSerializer,
        responses={
            201: WarrantyDocumentUploadResponseSerializer,
            400: OpenApiResponse(description="Invalid document upload request."),
            **ERRORS,
            503: OpenApiResponse(description="Warranty document storage is unavailable."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        warranty = resolve_warranty(request.user, pk)
        enforce(request.user, warranty)
        serializer = WarrantyDocumentPresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ext = storage.ext_for(data["content_type"], data["filename"])
        object_key = storage.warranty_object_key(warranty.makerspace_id, warranty.pk, ext)
        try:
            upload = storage.presigned_upload(object_key, data["content_type"])
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(
            {"object_key": object_key, "upload": upload},
            status=status.HTTP_201_CREATED,
        )


class WarrantyDocumentCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin warranty"],
        summary="List documents attached to a warranty",
        responses={200: WarrantyDocumentSerializer(many=True), **ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        warranty = resolve_warranty(request.user, pk)
        enforce(request.user, warranty)
        documents = warranty.documents.order_by("-created_at", "-id")
        return Response(WarrantyDocumentSerializer(documents, many=True).data)

    @extend_schema(
        tags=["Admin warranty"],
        summary="Finalize an uploaded warranty document",
        request=WarrantyDocumentFinalizeSerializer,
        responses={
            201: WarrantyDocumentSerializer,
            400: OpenApiResponse(description="Invalid or duplicate warranty document."),
            **ERRORS,
            503: OpenApiResponse(description="Warranty document storage is unavailable."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        warranty = resolve_warranty(request.user, pk)
        with storage_lifecycle(warranty.makerspace_id) as guard:
            warranty = resolve_warranty(request.user, pk)
            guard.verify(warranty.makerspace_id)
            enforce(request.user, warranty)
            serializer = WarrantyDocumentFinalizeSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            object_key = data["object_key"]
            existing = WarrantyDocument.objects.filter(warranty=warranty, object_key=object_key).first()
            if existing is not None:
                return Response(WarrantyDocumentSerializer(existing).data, status=status.HTTP_201_CREATED)
            storage.assert_warranty_object_key_for_makerspace(
                object_key, warranty.makerspace_id, warranty.pk,
            )
            if private_key_in_use(object_key):
                raise ValidationError({"object_key": "This object is already attached."})
            try:
                result = storage.prepare_upload(object_key)
            except StorageUnavailable:
                return storage_unavailable_response()
            guard.verify()
            try:
                with transaction.atomic():
                    makerspace = require_module_locked(
                        warranty.makerspace_id,
                        "machines" if warranty.machine_id else "staff_admin",
                        no_key=True,
                    )
                    Warranty.objects.select_for_update().get(pk=pk)
                    warranty = resolve_warranty(request.user, pk)
                    guard.verify(warranty.makerspace_id)
                    warranty.makerspace = makerspace
                    enforce(request.user, warranty)
                    storage.assert_warranty_object_key_for_makerspace(
                        object_key, warranty.makerspace_id, warranty.pk,
                    )
                    if private_key_in_use(object_key):
                        raise ValidationError({"object_key": "This object is already attached."})
                    charged = limits.add_storage(makerspace, result.size, no_key=True)
                    document = WarrantyDocument.objects.create(
                        warranty=warranty,
                        object_key=object_key,
                        original_filename=data["original_filename"],
                        content_type=result.content_type,
                        size_bytes=result.size,
                        uploaded_by=request.user,
                    )
                    audit.record(
                        request.user,
                        "warranty.document_added",
                        makerspace=warranty.makerspace,
                        target=document,
                        meta=(charge_metadata(
                            document, makerspace_id=makerspace.pk, size_bytes=result.size,
                        ) if charged is True else None),
                    )
                    return Response(
                        WarrantyDocumentSerializer(document).data,
                        status=status.HTTP_201_CREATED,
                    )
            except DocumentChargeProofUnavailable:
                return storage_unavailable_response()


class WarrantyDocumentUrlView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin warranty"],
        summary="Create a signed warranty document view URL",
        responses={
            200: WarrantyDocumentUrlSerializer,
            **ERRORS,
            503: OpenApiResponse(description="Warranty document storage is unavailable."),
        },
    )
    def get(self, request, pk, *args, **kwargs):
        document = resolve_document(request.user, pk)
        enforce(request.user, document.warranty)
        try:
            url = storage.presigned_get_url(document.object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response({"url": url})


class WarrantyDocumentDeleteView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin warranty"],
        summary="Delete a warranty document",
        responses={204: None, **ERRORS},
    )
    def delete(self, request, pk, *args, **kwargs):
        document = resolve_document(request.user, pk)
        warranty = document.warranty
        with storage_lifecycle(warranty.makerspace_id) as guard:
            enforce(request.user, warranty)
            guard.verify()
            with transaction.atomic():
                WarrantyDocument.objects.select_for_update().get(pk=pk)
                document = resolve_document(request.user, pk)
                warranty = document.warranty
                guard.verify(warranty.makerspace_id)
                enforce(request.user, warranty)
                audit.record(
                    request.user,
                    "warranty.document_removed",
                    makerspace=warranty.makerspace,
                    target=document,
                )
                # The signal reuses this ownership after commit. Unguarded
                # cascading deletes are refused rather than locking underneath SQL.
                document._storage_guard = guard
                document.delete()
                return Response(status=status.HTTP_204_NO_CONTENT)
