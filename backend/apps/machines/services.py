"""Audited workflow services for machine mutations."""

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import record
from apps.inventory import public_image_storage
from apps.machines import access, storage
from apps.machines.models import (
    Machine, MachineDocument, MachineErrorLog, MachineOperator, MachineUsageEntry,
)
from apps.machines.usage_totals import machine_usage_total
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module, require_module_locked
from apps.object_storage_lifecycle import storage_lifecycle


def _retired(machine):
    if not machine.is_active:
        raise ValidationError("Machine is retired.")


def _audit(machine, actor, action, meta=None):
    return record(
        actor, action, makerspace=machine.makerspace, target=machine,
        target_type="machine", meta=meta or {},
    )


@transaction.atomic
def set_status(machine, actor, status):
    if status not in Machine.Status.values:
        raise ValidationError({"status": "Invalid machine status."})
    _retired(machine)
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    _retired(machine)
    old_status = machine.status
    machine.status = status
    machine.save(update_fields=["status", "updated_at"])
    _audit(machine, actor, "machine.status_changed", {"old": old_status, "new": status})
    return machine


@transaction.atomic
def log_usage(machine, actor, hours, note=""):
    _retired(machine)
    if hours <= 0:
        raise ValidationError({"hours": "Hours must be greater than zero."})
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    _retired(machine)
    entry = MachineUsageEntry.objects.create(
        machine=machine,
        hours=hours,
        source=MachineUsageEntry.Source.MANUAL,
        note=note,
        logged_by=actor,
    )
    _audit(machine, actor, "machine.usage_logged", {"hours": str(hours), "note": note})
    return entry


def update_image(machine, actor, object_key, *, size_bytes=None, guard=None):
    with storage_lifecycle(machine.makerspace_id, guard=guard) as owned:
        if size_bytes is None:
            result = public_image_storage.finalize_upload(object_key)
            if result.status != "ok":
                raise ValidationError({"object_key": public_image_storage.finalize_error_message(result)})
            size_bytes = result.size
        owned.verify()
        with transaction.atomic():
            return _update_image(machine, actor, object_key, size_bytes=size_bytes, guard=owned)


def _update_image(machine, actor, object_key, *, size_bytes, guard):
    machine = Machine.objects.select_for_update(of=("self",)).select_related("makerspace").get(
        pk=machine.pk
    )
    guard.verify(machine.makerspace_id)
    require_module(machine.makerspace_id, "machines")
    if not access.can_manage_machine(actor, machine):
        raise PermissionDenied()
    old_key = machine.image_key
    if object_key and object_key != old_key and public_image_storage.public_image_key_in_use(
        machine.makerspace_id,
        object_key,
        machine_id=machine.pk,
    ):
        raise ValidationError({"object_key": "This image is already in use."})
    if old_key == object_key:
        return machine
    limits.add_storage(machine.makerspace, size_bytes)
    if old_key and old_key != object_key:
        public_image_storage.release_public_image_on_commit(
            machine.makerspace, old_key, guard=guard
        )
    machine.image_key = object_key
    machine.save(update_fields=["image_key", "updated_at"])
    _audit(machine, actor, "machine.image_updated")
    return machine


def remove_image(machine, actor, *, guard=None):
    with storage_lifecycle(machine.makerspace_id, guard=guard) as owned:
        owned.verify()
        with transaction.atomic():
            return _remove_image(machine, actor, guard=owned)


def _remove_image(machine, actor, *, guard):
    machine = Machine.objects.select_for_update(of=("self",)).select_related("makerspace").get(
        pk=machine.pk
    )
    guard.verify(machine.makerspace_id)
    require_module(machine.makerspace_id, "machines")
    if not access.can_manage_machine(actor, machine):
        raise PermissionDenied()
    if machine.image_key:
        public_image_storage.release_public_image_on_commit(
            machine.makerspace, machine.image_key, guard=guard
        )
    machine.image_key = ""
    machine.save(update_fields=["image_key", "updated_at"])
    _audit(machine, actor, "machine.image_removed")
    return machine


@transaction.atomic
def assign_operator(machine, actor, user, access_level):
    _retired(machine)
    if access_level not in MachineOperator.AccessLevel.values:
        raise ValidationError({"access_level": "Invalid operator access level."})
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    _retired(machine)
    if not access.is_active_member(user, machine.makerspace_id):
        raise ValidationError({"user": "User is not an active makerspace member."})
    existing = MachineOperator.objects.filter(machine=machine, user=user).first()
    existing_level = existing.access_level if existing else None
    if not access.can_assign_operator(
        actor,
        machine,
        target_level=access_level,
        existing_level=existing_level,
    ):
        raise PermissionDenied()
    row, created = MachineOperator.objects.update_or_create(
        machine=machine,
        user=user,
        defaults={"access_level": access_level, "assigned_by": actor},
    )
    action = "machine.operator_assigned" if created else "machine.operator_updated"
    _audit(
        machine,
        actor,
        action,
        {"user_id": user.pk, "access_level": access_level, "old_access_level": existing_level},
    )
    return row


@transaction.atomic
def remove_operator(machine, actor, user):
    _retired(machine)
    row = MachineOperator.objects.filter(machine=machine, user=user).first()
    if row is None:
        return
    if not access.can_assign_operator(
        actor,
        machine,
        target_level=row.access_level,
        existing_level=row.access_level,
    ):
        raise PermissionDenied()
    access_level = row.access_level
    row.delete()
    _audit(
        machine,
        actor,
        "machine.operator_removed",
        {"user_id": user.pk, "access_level": access_level},
    )


@transaction.atomic
def retire_machine(machine, actor):
    if not access.can_retire_machine(actor, machine):
        raise PermissionDenied()
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    old_status = machine.status
    machine.is_active = False
    machine.status = Machine.Status.OFFLINE
    machine.save(update_fields=["is_active", "status", "updated_at"])
    _audit(machine, actor, "machine.retired", {"old_status": old_status})
    return machine


@transaction.atomic
def unretire_machine(machine, actor):
    if not access.can_unretire_machine(actor, machine):
        raise PermissionDenied()
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    require_module_locked(machine.makerspace, "machines")
    limits.check_quota(machine.makerspace, "machines", adding=1)
    machine.is_active = True
    machine.save(update_fields=["is_active", "updated_at"])
    _audit(machine, actor, "machine.unretired")
    return machine


@transaction.atomic
def log_error(machine, actor, severity, message):
    _retired(machine)
    if severity not in MachineErrorLog.Severity.values:
        raise ValidationError({"severity": "Invalid error severity."})
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    _retired(machine)
    row = MachineErrorLog.objects.create(
        machine=machine,
        severity=severity,
        message=message,
        logged_by=actor,
    )
    _audit(machine, actor, "machine.error_logged", {"severity": severity})
    return row


def attach_document(machine, actor, object_key, doc_type, original_filename):
    from apps.machines.document_lifecycle import attach_document as implementation

    return implementation(machine, actor, object_key, doc_type, original_filename)


def remove_document(machine, actor, document):
    from apps.machines.document_lifecycle import remove_document as implementation

    return implementation(machine, actor, document)
