"""Validation and cross-model ownership checks for public image keys."""

from django.conf import settings
from django.db.models import Q
from rest_framework.exceptions import ValidationError


def public_image_key_in_use(
    makerspace_id, object_key, *, product_id=None, machine_id=None, event_id=None,
    series_id=None, profile_id=None, project_id=None, space_id=None, makerspace_field="",
):
    from django.apps import apps
    from apps.backup.object_ownership_registry import FIELD_OBJECT_RULES

    own_ids = {
        "inventory.InventoryProduct": product_id, "machines.Machine": machine_id,
        "events.Event": event_id, "events.EventSeries": series_id,
        "makerspaces.MemberProfile": profile_id, "makerspaces.MemberProject": project_id,
        "bookings.BookableSpace": space_id,
    }
    for rule in FIELD_OBJECT_RULES:
        if rule.bucket != "public_image":
            continue
        queryset = apps.get_model(rule.model_label)._base_manager.filter(**{rule.field_name: object_key})
        own_id = own_ids.get(rule.model_label)
        if own_id is not None:
            queryset = queryset.exclude(pk=own_id)
        if rule.model_label == "makerspaces.Makerspace" and rule.field_name == makerspace_field:
            queryset = queryset.exclude(pk=makerspace_id)
        # Inherited occurrence artwork resolves through its series; a non-empty
        # Event.image_key is an independent owner, including an explicit override.
        if queryset.exists():
            return True
    return False


def public_url(object_key):
    if not object_key:
        return ""
    if settings.PUBLIC_IMAGE_BASE_URL:
        return f"{settings.PUBLIC_IMAGE_BASE_URL.rstrip('/')}/{object_key}"
    return (
        f"{settings.AWS_S3_PUBLIC_ENDPOINT_URL.rstrip('/')}/"
        f"{settings.PUBLIC_IMAGE_BUCKET}/{object_key}"
    )


def ext_for(content_type, filename):
    allowed_exts = settings.PUBLIC_IMAGE_ALLOWED_MIME.get(content_type)
    if not allowed_exts:
        raise ValidationError({"content_type": "Unsupported public image content type."})
    safe_name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = f".{safe_name.rsplit('.', 1)[-1].lower()}" if "." in safe_name else ""
    if ext not in allowed_exts:
        raise ValidationError(
            {"filename": "Filename extension does not match the content type."}
        )
    return ext
