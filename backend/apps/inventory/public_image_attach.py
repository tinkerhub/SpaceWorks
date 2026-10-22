"""Promote and validate a presigned inventory image upload before it is attached."""

from apps.inventory import public_image_storage


class PublicImageRejected(Exception):
    """The object key cannot be attached; the message is safe to show the caller."""


def finalize_product_image(makerspace_id, object_key, *, product_id=None):
    """Run the attach pipeline for `object_key` and return its size in bytes.

    Ownership, key-in-use, finalize (staging -> final, size bounds) and the Pillow sniff
    all run here, so every attach path -- the image endpoint and bulk import alike --
    accepts only an uploaded, size-bounded, decodable image in this makerspace. A rejected
    upload's objects are deleted. Raises PublicImageRejected, or StorageUnavailable when
    object storage cannot be reached.
    """
    if not object_key.startswith(f"items/{makerspace_id}/"):
        raise PublicImageRejected("Image object key is outside this makerspace.")
    if not public_image_storage.is_safe_object_key(object_key):
        raise PublicImageRejected("Invalid image object key.")
    if public_image_storage.public_image_key_in_use(
        makerspace_id, object_key, product_id=product_id
    ):
        raise PublicImageRejected("This image is already in use.")
    result = public_image_storage.finalize_upload(object_key)
    if result.status != "ok":
        if result.status in {"empty", "too_large"}:
            _delete_upload(object_key)
        raise PublicImageRejected(public_image_storage.finalize_error_message(result))
    if not public_image_storage.sniff_is_valid_image(object_key):
        _delete_upload(object_key)
        raise PublicImageRejected("Uploaded file is not a valid image.")
    return result.size


def _delete_upload(object_key):
    public_image_storage.delete_object(object_key)
    public_image_storage.delete_object(public_image_storage.staging_key(object_key))
