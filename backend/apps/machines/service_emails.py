"""Fail-safe notification seam for machine-service lifecycle events."""

import logging
from urllib.parse import quote

from apps.notifications.emit import emit_notification

logger = logging.getLogger(__name__)


def notify_service_status(service_request, event):
    """Emit a staff notification without allowing delivery to break the workflow."""
    try:
        from apps.machines.service_printing_emails import (
            _is_printer_request, notify_printer_service_status,
        )
        if _is_printer_request(service_request):
            notify_printer_service_status(service_request, event)
        else:
            from apps.machines.service_notifications import notify_machine_service_status

            notify_machine_service_status(service_request, event)
    except Exception:
        logger.exception("machine_service_lifecycle_notification_failed", extra={"request_id": getattr(service_request, "pk", None), "event": event})
    try:
        makerspace = service_request.makerspace
        machine_type = (
            service_request.queue.machine_type if service_request.queue_id
            else service_request.bucket.machine.machine_type
        )
        segment = str(machine_type.pk)
        if machine_type.slug:
            segment += "-" + quote(machine_type.slug, safe="")
        tenant_domain = (
            makerspace.frontend_domain
            and makerspace.frontend_domain_status == "verified"
        )
        prefix = "/admin" if tenant_domain else f"/m/{quote(makerspace.slug, safe='')}/admin"
        emit_notification(
            makerspace,
            event=f"machine_service.{event}",
            title="Machine service request updated",
            body=(
                f"Machine service request #{service_request.pk} {event}. "
                f"Status: {service_request.status}."
            ),
            url_path=f"{prefix}/machines/{segment}",
        )
    except Exception:
        logger.exception(
            "machine_service_notification_failed",
            extra={"request_id": getattr(service_request, "pk", None), "event": event},
        )
