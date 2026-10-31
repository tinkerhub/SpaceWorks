"""Prepare admin uploads before Django opens its change-form transaction."""
from django.contrib import messages
from rest_framework.exceptions import ValidationError

from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage as storage
from apps.object_storage_lifecycle import storage_lifecycle


def prepare_images(admin, request, obj, specs):
    from django.conf import settings

    prepared = {}
    for upload_field, kind in specs:
        upload = request.FILES.get(upload_field)
        if upload is None:
            continue
        try:
            ext = storage.ext_for(upload.content_type, upload.name)
            data = upload.read(settings.PUBLIC_IMAGE_MAX_BYTES + 1)
            upload.seek(0)
            if not 1 <= len(data) <= settings.PUBLIC_IMAGE_MAX_BYTES:
                raise ValidationError("Invalid image size.")
            tenant = obj.pk if kind == "makerspace" else obj.makerspace_id
            key = storage.build_object_key(kind, tenant, ext)
            storage.put_bytes(storage.staging_key(key), data, upload.content_type)
            result = storage.finalize_upload(key)
            if result.status != "ok":
                raise ValidationError(storage.finalize_error_message(result))
            prepared[upload_field] = (key, result.size)
        except (ValidationError, StorageUnavailable):
            admin.message_user(request, "The image could not be validated or stored; it was not saved.", level=messages.ERROR)
    return prepared


class AdminImageLifecycleMixin:
    """A request owns the explicit guard until admin commit and cleanup finish."""

    def storage_image_specs(self):
        return (("image_upload", self.image_kind),)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST" or object_id is None:
            return super().changeform_view(request, object_id, form_url, extra_context)
        obj = self.get_object(request, object_id)
        if obj is None or not self.has_change_permission(request, obj):
            return super().changeform_view(request, object_id, form_url, extra_context)
        specs = self.storage_image_specs()
        tenant = obj.pk if specs[0][1] == "makerspace" else obj.makerspace_id
        with storage_lifecycle(tenant) as guard:
            request._storage_guard = guard
            request._prepared_storage_images = prepare_images(self, request, obj, specs)
            guard.verify()
            return super().changeform_view(request, object_id, form_url, extra_context)
