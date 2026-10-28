"""Explicit, idempotent staff setup for the public built-in printer queue."""
from django.db import transaction
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.machines import role_scope
from apps.machines.models import ServiceQueue
from apps.machines.printer_capabilities import is_printer_type, resolve_global_printer_type
from apps.makerspaces.guards import require_module, require_module_locked

DEFAULT_PUBLIC_QUEUE_NAME = "Public Requests"


class PublicQueueNameConflict(APIException):
    status_code = 409
    default_code = "public_queue_name_conflict"
    default_detail = {
        "detail": "Public Requests is already used by another machine type. Rename that queue before enabling public print requests.",
        "code": "public_queue_name_conflict",
    }


def can_manage_public_queue(actor, makerspace_id, machine_type=None):
    printer = machine_type if machine_type is not None else resolve_global_printer_type()
    return bool(
        printer is not None and is_printer_type(printer) and printer.is_builtin
        and rbac.can(actor, rbac.Action.MANAGE_MACHINES, makerspace_id)
        and role_scope.scope_covers_type(
            role_scope.manage_scope_for(actor, makerspace_id), printer
        )
    )


def _require_setup(actor, makerspace, *, locked=False):
    for key in ("machines", "machine_service", "printing"):
        makerspace = (
            require_module_locked(makerspace, key, no_key=True)
            if locked else require_module(makerspace, key)
        )
    printer = resolve_global_printer_type()
    if printer is None:
        raise ValidationError({"machine_type": "The built-in printer type is not installed."})
    if not can_manage_public_queue(actor, makerspace.pk, printer):
        raise PermissionDenied()
    return makerspace, printer


def _active_queue(makerspace, printer, *, locked=False):
    rows = ServiceQueue.objects.filter(
        makerspace=makerspace, machine_type=printer, is_active=True
    ).order_by("name", "pk")
    return (rows.select_for_update() if locked else rows).first()


def _state(queue):
    return {
        "enabled": queue is not None,
        "queue_id": queue.pk if queue else None,
        "name": queue.name if queue else None,
    }


def public_queue_state(actor, makerspace):
    space, printer = _require_setup(actor, makerspace)
    return _state(_active_queue(space, printer))


@transaction.atomic
def enable_public_queue(actor, makerspace):
    # The makerspace lock precedes queue locks, and serializes setup with uninstall
    # and another setup POST, including the first-ever queue creation.
    space, printer = _require_setup(actor, makerspace, locked=True)
    active = _active_queue(space, printer, locked=True)
    if active is not None:
        return _state(active)
    queue = ServiceQueue.objects.select_for_update().filter(
        makerspace=space, name=DEFAULT_PUBLIC_QUEUE_NAME
    ).first()
    if queue is not None and queue.machine_type_id != printer.pk:
        raise PublicQueueNameConflict()
    if queue is None:
        queue = ServiceQueue.objects.create(
            makerspace=space, machine_type=printer, name=DEFAULT_PUBLIC_QUEUE_NAME
        )
        action = "machine_service.public_queue_created"
    else:
        queue.is_active = True
        queue.save(update_fields=["is_active", "updated_at"])
        action = "machine_service.public_queue_activated"
    audit.record(actor, action, makerspace=space, target=queue)
    return _state(queue)
