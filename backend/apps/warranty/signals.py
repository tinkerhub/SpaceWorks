"""Guard-reusing cleanup for explicit and cascading document deletion."""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.document_storage_quota import proven_document_charge, release_charge_once
from apps.evidence.storage import StorageUnavailable

from apps.warranty.models import WarrantyDocument
from apps.object_storage_lifecycle import storage_lifecycle
from apps.object_storage_references import private_key_in_use


@receiver(post_delete, sender=WarrantyDocument)
def delete_warranty_document_object(sender, instance, origin=None, **kwargs):
    from apps.warranty import storage
    from apps.makerspaces.purge_cleanup import owns_cleanup

    makerspace_id = instance.warranty.makerspace_id
    if owns_cleanup(makerspace_id) or not instance.object_key:
        return
    guard = getattr(origin, "_storage_guard", None) or getattr(instance, "_storage_guard", None)
    if guard is None:
        # Refuse the delete transaction. Acquiring a guard from post_delete would
        # invert row-lock order and would not protect the detachment boundary.
        raise StorageUnavailable
    guard.verify(makerspace_id)
    key = instance.object_key
    # Freeze target PK + incarnation before Django clears instance.pk.
    charge = proven_document_charge(instance, makerspace_id=makerspace_id)

    def delete_after_commit():
        with storage_lifecycle(makerspace_id, guard=guard):
            if not private_key_in_use(key):
                guard.verify(makerspace_id)
                if charge is None:
                    storage.delete_object(key)
                    return
                deleted = storage.delete_object(key, report_versions=True)
                if type(deleted) is not frozenset or not deleted:
                    return

                def verify_release():
                    guard.verify(makerspace_id)
                    if private_key_in_use(key):
                        raise StorageUnavailable

                verify_release()
                release_charge_once(charge, verify=verify_release)

    transaction.on_commit(delete_after_commit)
