"""Real terminal rows shared by the two finite reprint regression files."""

from copy import deepcopy

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.integrations.models import DailyNotificationCounter, EmailLog, NotificationDeliveryLog
from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue, ServiceRequestFile
from apps.machines.printer_capabilities import PRINTER_CONFIG
from apps.notifications.models import Notification
from tests.own_requests.own_requests_support import service
from tests.return_helpers import make_member


@pytest.fixture
def reprint_lab(history_lab):
    lab = history_lab
    lab.actor = make_member("reprint-manager", lab.space)
    lab.space.telegram_group_chat_id = "-101101"
    lab.space.save(update_fields=["telegram_group_chat_id"])
    return lab


def terminal_request(lab, *, printer=False):
    queue = lab.queue
    if printer:
        kind, _ = MachineType.objects.get_or_create(
            makerspace=None, slug="3d_printer", defaults={
                "name": "3D Printer", "is_builtin": True, "managing_action": "manage_printing",
                "capability_config": deepcopy(PRINTER_CONFIG),
            },
        )
        queue = ServiceQueue.objects.create(makerspace=lab.space, machine_type=kind, name="Reprint queue")
    original = service(
        lab, queue=queue, member=lab.user, requester=lab.actor, status="failed",
        requester_name="Private reprint borrower", contact_email="reprint-private@example.test",
        contact_phone="+15551239876", source_link="https://private.invalid/reprint.stl",
        reason="Private failed-run reason", estimated_minutes=7,
    )
    attachment = ServiceRequestFile.objects.create(
        service_request=original, makerspace=lab.space, queue=queue,
        kind="attachment", object_key=f"reprints/{original.pk}/private-plan.pdf",
        original_filename="private-plan.pdf", content_type="application/pdf", size_bytes=23,
        owner_user_id=lab.user.pk, attached_at=timezone.now(),
    )
    return original, attachment


def effects(lab, providers):
    """Include durable writes and the actual captured provider boundary."""
    models = (
        MachineServiceRequest, AuditLog, DailyNotificationCounter,
        NotificationDeliveryLog, EmailLog, Notification,
    )
    return (
        tuple(list(model.objects.filter(makerspace=lab.space).order_by("pk").values())
              for model in models),
        list(providers),
    )
