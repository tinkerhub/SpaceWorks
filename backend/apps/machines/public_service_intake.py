"""Transactional public type intake over the existing service workflow and storage."""
from types import SimpleNamespace

from django.db import transaction
from apps.object_storage_lifecycle import storage_lifecycle
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from apps.machines.service_file_lifecycle import prepare_files
from rest_framework.exceptions import NotFound, ValidationError

from apps.encryption.write_fence import assert_mapped_write_allowed
from apps.machines import service_workflow
from apps.machines.models import MachineServiceRequest, ServiceRequestFile
from apps.machines.print_uploads import validate_print_upload
from apps.machines.printer_capabilities import is_printer_type
from apps.machines.public_printer_service import _kernel_payload
from apps.machines.public_service_catalog import (
    public_type_policy, resolve_public_service_type,
)
from apps.machines.public_service_queue import (
    attachment_queue_id, lock_attachments, resolve_intake_queue, validate_requested_queue,
)
from apps.machines.service_queue_position import queue_counts_for
from apps.machines.service_storage import create_staged_queue_file, finalize_file, validate_upload_declaration
from apps.machines.service_workflow_helpers import _validate_capability_payload
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_queryset


def _locked_space(makerspace):
    # PII maintenance takes the fence before row locks. NO KEY UPDATE serializes
    # module/quota writers while letting staff finish audit FK checks on the space.
    assert_mapped_write_allowed(makerspace.pk)
    return Makerspace.objects.select_for_update(no_key=True).get(pk=makerspace.pk)


def _payload(machine_type, makerspace, data):
    if is_printer_type(machine_type):
        payload = _kernel_payload(SimpleNamespace(machine_type=machine_type, makerspace=makerspace), data)
    else:
        payload = {}
    _validate_capability_payload(machine_type, payload)
    return payload


def submit_typed_request(makerspace, data, actor, *, supplied_printer_fields=()):
    ids = tuple(data.get("file_ids") or ())
    context = storage_lifecycle(makerspace.pk) if ids else boundary_tenant_write(makerspace.pk)
    with context as guard:
        # Reject invalid input before publication, without creating or locking queues.
        machine_type = resolve_public_service_type(makerspace, data["machine_type_id"])
        if not is_printer_type(machine_type) and supplied_printer_fields:
            raise ValidationError("Printer fields require a printer machine type.")
        _payload(machine_type, makerspace, data)
        queue_id = attachment_queue_id(makerspace, actor, ids, data.get("queue_id"))
        validate_requested_queue(makerspace, machine_type, queue_id)
        # Preparation cannot hold application row locks; metadata below repeats
        # policy/queue/ownership checks before publishing the request.
        prepared = {}
        if ids:
            prepared = prepare_files(makerspace.pk, ids, actor, guard)
            guard.verify()
        with transaction.atomic():
            space = _locked_space(makerspace)
            machine_type = resolve_public_service_type(space, data["machine_type_id"])
            if not is_printer_type(machine_type) and supplied_printer_fields:
                raise ValidationError("Printer fields require a printer machine type.")
            payload = _payload(machine_type, space, data)
            queue_id = attachment_queue_id(space, actor, ids, data.get("queue_id"))
            queue = resolve_intake_queue(space, machine_type, actor, queue_id=queue_id)
            files = lock_attachments(space, actor, ids, queue)
            if is_printer_type(machine_type):
                limits.check_quota(space, "print", adding=1, no_key=True)
            row = service_workflow.submit(
                queue, actor, member=actor, actor=actor,
                requester_name=actor.display_name or "", contact_email=actor.email or "",
                contact_phone=actor.phone or "", title=data["title"],
                description=data.get("description", ""), source_link=data.get("source_link", ""),
                capability_payload=payload,
            )
            for file in files:
                finalize_file(row, file_id=file.pk, actor=actor, guard=guard, prepared=prepared[file.pk])
            return row


def validate_type_upload(machine_type, data):
    if is_printer_type(machine_type):
        try:
            content_type = validate_print_upload(data.get("kind"), data["filename"], data.get("content_type", ""))
        except ValueError as exc:
            raise ValidationError({"file": str(exc)}) from exc
        kind = ServiceRequestFile.Kind.MODEL if data["kind"] == "stl" else ServiceRequestFile.Kind.SCREENSHOT
    else:
        if data.get("kind", "attachment") != "attachment":
            raise ValidationError({"kind": "This machine type accepts attachments."})
        kind, content_type = ServiceRequestFile.Kind.ATTACHMENT, data.get("content_type", "")
    validate_upload_declaration(public_type_policy(machine_type), data["filename"], content_type)
    return kind, content_type


@transaction.atomic
def stage_typed_upload(makerspace, data, actor):
    space = _locked_space(makerspace)
    machine_type = resolve_public_service_type(space, data["machine_type_id"])
    # Validate before the first queue write or storage call; presigning failure rolls
    # back the queue, staged row and their audit entries in this same transaction.
    kind, content_type = validate_type_upload(machine_type, data)
    queue = resolve_intake_queue(space, machine_type, actor, queue_id=data.get("queue_id"))
    upload, presigned = create_staged_queue_file(
        queue, actor=actor, filename=data["filename"], content_type=content_type, kind=kind,
    )
    return {"queue_id": queue.pk, "file_id": upload.pk, "upload": presigned}


def public_service_status(public_token):
    row = servable_queryset(MachineServiceRequest.objects.select_related(
        "makerspace", "queue__machine_type", "bucket__machine__machine_type",
    ).filter(public_token=public_token), relation="makerspace").first()
    if row is None or not all(module_enabled(row.makerspace, key) for key in ("machines", "machine_service")):
        raise NotFound()
    machine_type = row.queue.machine_type if row.queue_id else row.bucket.machine.machine_type
    if is_printer_type(machine_type) and not module_enabled(row.makerspace, "printing"):
        raise NotFound()
    return row, queue_counts_for([row])
