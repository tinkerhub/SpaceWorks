"""Machine manuals share storage exclusion with maintenance documents."""
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import record
from apps.machines import access, storage
from apps.machines.models import Machine, MachineDocument
from apps.makerspaces.guards import require_module
from apps.object_storage_lifecycle import storage_lifecycle
from apps.object_storage_references import private_key_in_use


def assert_unused(key):
    if private_key_in_use(key):
        raise ValidationError({"object_key": "This document is already attached."})


def attach_document(machine, actor, object_key, doc_type, original_filename):
    if doc_type not in MachineDocument.DocType.values:
        raise ValidationError({"doc_type": "Invalid machine document type."})
    with storage_lifecycle(machine.makerspace_id) as guard:
        require_module(machine.makerspace_id, "machines")
        if not access.can_manage_machine(actor, machine):
            raise PermissionDenied()
        existing = MachineDocument.objects.filter(machine=machine, object_key=object_key).first()
        if existing is not None:
            return existing
        storage.assert_machine_object_key_for_makerspace(
            object_key, machine.makerspace_id, machine.pk,
        )
        assert_unused(object_key)
        result = storage.prepare_upload(object_key)
        guard.verify()
        with transaction.atomic():
            machine = Machine.objects.select_for_update().get(pk=machine.pk)
            require_module(machine.makerspace_id, "machines")
            if not access.can_manage_machine(actor, machine):
                raise PermissionDenied()
            storage.assert_machine_object_key_for_makerspace(
                object_key, machine.makerspace_id, machine.pk,
            )
            assert_unused(object_key)
            guard.verify()
            doc = MachineDocument.objects.create(
                machine=machine, doc_type=doc_type, object_key=object_key,
                original_filename=original_filename, content_type=result.content_type,
                size_bytes=result.size, uploaded_by=actor,
            )
            record(actor, "machine.document_added", makerspace=machine.makerspace,
                   target=machine, target_type="machine",
                   meta={"document_id": doc.pk, "doc_type": doc_type, "object_key": object_key})
            return doc


def remove_document(machine, actor, document):
    with storage_lifecycle(machine.makerspace_id) as guard:
        with transaction.atomic():
            machine = Machine.objects.select_for_update().get(pk=machine.pk)
            require_module(machine.makerspace_id, "machines")
            if not access.can_manage_machine(actor, machine):
                raise PermissionDenied()
            document = MachineDocument.objects.select_for_update().get(pk=document.pk, machine=machine)
            key, document_id = document.object_key, document.pk
            guard.verify()
            document.delete()
            record(actor, "machine.document_removed", makerspace=machine.makerspace,
                   target=machine, target_type="machine",
                   meta={"document_id": document_id, "object_key": key})
        guard.verify()
        if not private_key_in_use(key):
            guard.verify()
            storage.delete_object(key)
