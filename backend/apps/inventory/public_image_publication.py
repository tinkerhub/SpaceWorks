"""Snapshot validation shared by inventory and booking image publication."""
from dataclasses import dataclass
import time

from django.conf import settings

from apps.evidence.image_validation import image_mime_from_bytes
from apps.object_publication import InvalidObjectSize, publish


class InvalidImage(Exception):
    pass


@dataclass(frozen=True)
class ImageMetadata:
    size: int
    content_type: str


def validate_snapshot(observed):
    detected = image_mime_from_bytes(observed.data())
    if detected not in settings.PUBLIC_IMAGE_ALLOWED_MIME or detected != observed.content_type:
        raise InvalidImage
    return ImageMetadata(observed.size, detected)


def finalize(storage, object_key):
    try:
        for attempt in range(10):
            result = publish(
                storage._client(), bucket=settings.PUBLIC_IMAGE_BUCKET, key=object_key,
                staging_key=storage.staging_key(object_key), max_bytes=settings.PUBLIC_IMAGE_MAX_BYTES,
                validator=validate_snapshot,
            )
            if result is not None or attempt == 9:
                break
            time.sleep(0.2)
    except InvalidObjectSize as exc:
        return storage.FinalizeResult("empty" if exc.size == 0 else "too_large", exc.size)
    except InvalidImage:
        return storage.FinalizeResult("invalid", None)
    if result is None:
        return storage.FinalizeResult("missing", None)
    storage.delete_object(storage.staging_key(object_key))
    return storage.FinalizeResult("ok", result.size)
