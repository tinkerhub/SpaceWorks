from django.db import transaction
from apps.object_storage_lifecycle import storage_lifecycle
from apps.object_storage_references import private_key_in_use
from rest_framework.exceptions import ValidationError

from apps.audit.services import record
from apps.makerspaces import limits
from apps.maintenance import storage
from apps.maintenance.models import MaintenanceLog, MaintenanceLogDocument
from apps.maintenance.services_shared import lock_machine, prepare_machine


def finalize_log_document(log, *, actor, object_key):
    with storage_lifecycle(log.machine.makerspace_id) as guard:
        prepare_machine(log.machine, actor, manage=False)
        existing = MaintenanceLogDocument.objects.filter(log=log, object_key=object_key).first()
        if existing is not None:
            return existing
        storage.assert_log_document_object_key(object_key, log.machine.makerspace_id, log.machine_id)
        _assert_unused(object_key)
        result = storage.prepare_upload(object_key)
        guard.verify()
        with transaction.atomic():
            machine = lock_machine(log.machine)
            prepare_machine(machine, actor, manage=False)
            locked = MaintenanceLog.objects.select_for_update().get(pk=log.pk, machine=machine)
            _assert_unused(object_key)
            guard.verify()
            limits.add_storage(machine.makerspace, result.size)
            document = MaintenanceLogDocument.objects.create(
                log=locked, object_key=object_key, size_bytes=result.size, uploaded_by=actor,
            )
            record(actor, "maintenance.document_added", makerspace=machine.makerspace,
                   target=document, meta={"log_id": locked.pk, "machine_id": machine.pk, "size_bytes": result.size})
            return document


def _assert_unused(object_key):
    if private_key_in_use(object_key):
        raise ValidationError({"object_key": "This document is already attached."})


def delete_log_document(document, *, actor):
    with storage_lifecycle(document.log.machine.makerspace_id) as guard:
        with transaction.atomic():
            machine = lock_machine(document.log.machine)
            prepare_machine(machine, actor, manage=True)
            log = MaintenanceLog.objects.select_for_update().get(
                pk=document.log_id, machine=machine,
            )
            document = MaintenanceLogDocument.objects.select_for_update().get(
                pk=document.pk, log=log,
            )
            object_key = document.object_key
            size_bytes = document.size_bytes
            document_id = document.pk
            record(
                actor,
                "maintenance.document_deleted",
                makerspace=machine.makerspace,
                target=document,
                meta={
                    "document_id": document_id,
                    "log_id": log.pk,
                    "machine_id": machine.pk,
                    "size_bytes": size_bytes,
                },
            )
            guard.verify()
            document.delete()
        guard.verify()
        if not private_key_in_use(object_key):
            guard.verify()
            if storage.delete_object(object_key):
                guard.verify()
                limits.free_storage(machine.makerspace, size_bytes)
