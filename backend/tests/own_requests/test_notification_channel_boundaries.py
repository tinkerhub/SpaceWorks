"""Default Telegram delivery and existing preference/module/destination gates."""

from copy import deepcopy

import pytest

from apps.integrations.models import (
    DailyNotificationCounter, EmailLog, NotificationDeliveryLog, NotificationPreference,
)
from apps.integrations.models_destinations import NotificationDestination
from apps.integrations.staff_notifications import staff_emails_for_feature, staff_user_ids_for_feature
from apps.machines.models import MachineType, ServiceQueue
from apps.machines.printer_capabilities import PRINTER_CONFIG
from apps.notifications.models import Notification
from tests.own_requests.own_requests_support import history_lab, providers, submit_service
from tests.return_helpers import make_member

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("printer,gate", [
    (True, "default"), (True, "explicit_off"), (True, "feature_module"),
    (True, "channel_module"), (True, "unconfigured"), (True, "inactive_room"),
    (False, "explicit_off"), (False, "feature_module"),
    (False, "channel_module"), (False, "unconfigured"), (False, "inactive_room"),
])
def test_real_engine_keeps_printer_exclusive_and_respects_existing_gates(
    history_lab, providers, settings, django_capture_on_commit_callbacks, printer, gate,
):
    lab = history_lab
    feature = "printing" if printer else "machine_service"
    queue = lab.queue
    if printer:
        kind, _ = MachineType.objects.get_or_create(
            makerspace=None, slug="3d_printer", defaults={
                "name": "3D Printer", "is_builtin": True, "managing_action": "manage_printing",
                "capability_config": deepcopy(PRINTER_CONFIG),
            },
        )
        queue = ServiceQueue.objects.create(makerspace=lab.space, machine_type=kind, name="Printer queue")
    lab.space.telegram_group_chat_id = "-100801"
    lab.space.save(update_fields=["telegram_group_chat_id"])
    if gate == "explicit_off":
        NotificationPreference.objects.create(
            makerspace=lab.space, feature=feature, channel="telegram", enabled=False,
        )
    elif gate == "channel_module":
        lab.space.enabled_modules.remove("telegram")
        lab.space.save(update_fields=["enabled_modules"])
    elif gate == "unconfigured":
        settings.TELEGRAM_BOT_TOKEN = ""
    elif gate == "inactive_room":
        NotificationDestination.objects.create(
            makerspace=lab.space, channel="telegram", label="Inactive",
            telegram_chat_id="-100802", is_active=False,
        )

    with django_capture_on_commit_callbacks(execute=True):
        row = submit_service(lab, queue=queue)
        if gate == "feature_module":
            # Simulate uninstall between workflow scheduling and committed delivery.
            lab.space.enabled_modules.remove(feature)
            lab.space.save(update_fields=["enabled_modules"])

    assert Notification.objects.filter(event="machine_service.submitted").count() == 1
    logs = NotificationDeliveryLog.objects.all()
    assert not logs.exclude(feature=feature).exists()
    assert len(providers) == int(gate == "default")
    if gate == "default":
        log = logs.get()
        assert (log.channel, log.status, log.event) == ("telegram", "sent", "submitted")
        assert providers == [{"chat_id": "-100801", "text": log.text_body}]
        assert log.feature == "printing"
        # Existing requester mail remains exactly one Printing delivery.
        assert EmailLog.objects.filter(stream="printing", event="submitted", audience="requester").count() == 1
        assert not EmailLog.objects.filter(stream="machine_service").exists()
        assert str(row.public_token) not in log.text_body
    elif gate in {"explicit_off", "feature_module"}:
        assert not logs.exists()
    elif gate == "unconfigured":
        assert (logs.get().status, logs.get().error) == ("failed", "notification_channel_not_configured")
    else:
        assert logs.get().status == "skipped"
        expected = "notification_channel_module_disabled" if gate == "channel_module" else "notification_no_matching_destination"
        assert logs.get().error == expected


def test_staff_email_switch_does_not_mute_chat_and_still_suppresses_recipient_selectors(
    history_lab, providers, django_capture_on_commit_callbacks,
):
    lab = history_lab
    manager = make_member("email-switch-manager", lab.space)
    assert manager.email in staff_emails_for_feature(lab.space, "machine_service", event="submitted")
    assert manager.pk in staff_user_ids_for_feature(lab.space, "machine_service", event="submitted")
    lab.space.staff_notifications_enabled = False
    lab.space.telegram_group_chat_id = "-100901"
    lab.space.save(update_fields=["staff_notifications_enabled", "telegram_group_chat_id"])
    assert staff_emails_for_feature(lab.space, "machine_service", event="submitted") == []
    assert staff_user_ids_for_feature(lab.space, "machine_service", event="submitted") == []
    with django_capture_on_commit_callbacks(execute=True):
        submit_service(lab)
    assert len(providers) == 1
    assert NotificationDeliveryLog.objects.get().status == "sent"
    assert not EmailLog.objects.exists()


def test_managed_real_quota_counts_one_send_and_refuses_second(
    history_lab, providers, settings, django_capture_on_commit_callbacks,
):
    lab = history_lab
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    settings.INFRA_HOSTS = {"testserver"}
    lab.space.telegram_group_chat_id = "-101001"
    lab.space.resource_limit_overrides = {
        "telegram": 1, "machine_service_open": 10, "machine_service_submit": 10,
    }
    lab.space.save(update_fields=["telegram_group_chat_id", "resource_limit_overrides"])
    for _ in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            submit_service(lab)
    assert len(providers) == 1
    assert list(NotificationDeliveryLog.objects.order_by("pk").values_list("status", flat=True)) == ["sent", "failed"]
    assert NotificationDeliveryLog.objects.latest("pk").error == "Daily telegram notification limit reached for this space."
    counter = DailyNotificationCounter.objects.get()
    assert (counter.makerspace_id, counter.channel, counter.count) == (lab.space.pk, "telegram", 1)
    assert Notification.objects.filter(event="machine_service.submitted").count() == 2
