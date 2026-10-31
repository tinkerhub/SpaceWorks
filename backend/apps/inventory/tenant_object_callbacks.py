"""Synchronous post-commit cleanup under the lifecycle owner's explicit guard."""
from apps.object_storage_lifecycle import storage_lifecycle
from apps.object_storage_references import key_in_use


def release_public_image(makerspace, object_key, storage=None, *, guard):
    from apps.inventory import public_image_storage

    with storage_lifecycle(makerspace.pk, guard=guard):
        if object_key and not key_in_use("public_image", object_key):
            public_image_storage.release_public_image(makerspace, object_key, storage, guard=guard)


def delete_public_image(makerspace_id, object_key, *, guard):
    from apps.inventory import public_image_storage

    with storage_lifecycle(makerspace_id, guard=guard):
        if object_key and not key_in_use("public_image", object_key):
            guard.verify(makerspace_id)
            public_image_storage.delete_object(object_key)
