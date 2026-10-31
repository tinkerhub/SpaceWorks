"""Generic staff lifecycle alerts through the existing channel and scope engine."""

from apps.integrations.destinations import NotificationScope
from apps.integrations.notification_enums import NotificationFeature
from apps.integrations.notify import LifecyclePayload, notify_lifecycle
from apps.machines.models import MachineServiceRequest


def notify_machine_service_status(service_request, event):
    """Schedule a non-printer alert; re-read its canonical subject after commit.

    No requester email or new template stream is created. Delivery remains the
    existing best-effort fan-out, including preferences, room scopes and quotas.
    """
    request_id = service_request.pk

    def build():
        row = MachineServiceRequest.objects.select_related(
            "makerspace", "queue__machine_type", "assigned_machine__machine_type",
            "bucket__machine__machine_type",
        ).get(pk=request_id)
        machine = row.assigned_machine or (row.bucket.machine if row.bucket_id else None)
        machine_type = row.queue.machine_type if row.queue_id else row.bucket.machine.machine_type
        return LifecyclePayload(
            text=(
                f"Machine service request #{row.pk} {event}.\n"
                f"Type: {machine_type.name}\nTitle: {row.title}\n"
                f"Status: {row.status}\nReview and manage in the staff console."
            ),
            scope=NotificationScope(machine=machine, machine_type=machine_type),
        )

    return notify_lifecycle(
        service_request.makerspace,
        feature=NotificationFeature.MACHINE_SERVICE,
        event=event,
        build=build,
    )
