"""Real workflow commits reach the generic channel engine once per transition."""

import pytest
from django.db import transaction

from apps.audit.models import AuditLog
from apps.integrations.models import EmailLog, NotificationDeliveryLog
from apps.integrations.models_destinations import (
    DestinationMachineScope, DestinationMachineTypeScope, NotificationDestination,
)
from apps.machines import role_scope
from apps.machines.models import MachineServiceRequest, MachineType
from apps.machines.service_errors import ServiceInvalidTransition
from apps.machines.service_workflow import accept, collect, complete, fail, reject, start
from apps.notifications.models import Notification
from tests.own_requests.own_requests_support import (
    history_lab, providers, submit_service,
)

pytestmark = pytest.mark.django_db


def room(space, label, chat_id):
    return NotificationDestination.objects.create(
        makerspace=space, channel="telegram", label=label, telegram_chat_id=chat_id,
    )


def test_generic_all_lifecycle_events_commit_one_staff_and_one_channel_alert(
    history_lab, providers, django_capture_on_commit_callbacks,
):
    lab = history_lab
    lab.space.telegram_group_chat_id = "-100111"
    # Generic notifications must work independently of the Printing module.
    lab.space.enabled_modules.remove("printing")
    lab.space.save(update_fields=["telegram_group_chat_id", "enabled_modules"])

    def commit(operation, event):
        before = (Notification.objects.count(), NotificationDeliveryLog.objects.count(), len(providers))
        with django_capture_on_commit_callbacks(execute=True):
            row = operation()
        assert Notification.objects.count() == before[0] + 1
        assert NotificationDeliveryLog.objects.count() == before[1] + 1
        assert len(providers) == before[2] + 1
        inbox = Notification.objects.latest("pk")
        log = NotificationDeliveryLog.objects.latest("pk")
        assert inbox.event == f"machine_service.{event}"
        assert inbox.url_path == f"/m/{lab.space.slug}/admin/machines/{lab.kind.pk}-laser"
        assert (log.feature, log.event, log.channel, log.status, log.attempts) == (
            "machine_service", event, "telegram", "sent", 1,
        )
        assert providers[-1] == {"chat_id": "-100111", "text": log.text_body}
        for value in (f"#{row.pk}", lab.kind.name, row.title, f"Status: {row.status}"):
            assert value in log.text_body
        for secret in (str(row.public_token), row.contact_email, row.contact_phone,
                       row.source_link, "Private failure", "Private rejection"):
            if secret:
                assert secret not in log.text_body and secret not in inbox.body
        assert log.payload["scope"] == {
            "machine_id": row.assigned_machine_id,
            "machine_type_id": lab.kind.pk, "category_id": None,
        }
        return row

    row = commit(lambda: submit_service(lab), "submitted")
    assert row.assigned_machine_id is None
    row = commit(lambda: accept(row, lab.user), "accepted")
    row = commit(lambda: start(row, lab.user, role_scope.EXEMPT, machine_id=lab.machine.pk), "started")
    row = commit(lambda: complete(row, lab.user, actual_minutes=2, consumptions=[]), "completed")
    row = commit(lambda: collect(row, lab.user), "collected")
    rejected = commit(lambda: submit_service(lab), "submitted")
    commit(lambda: reject(rejected, lab.user, reason="Private rejection"), "rejected")
    failed = commit(lambda: submit_service(lab), "submitted")
    failed = commit(lambda: accept(failed, lab.user), "accepted")
    failed = commit(lambda: start(failed, lab.user, role_scope.EXEMPT, machine_id=lab.machine.pk), "started")
    commit(lambda: fail(failed, lab.user, reason="Private failure", percent_complete=10,
                        actual_minutes=1, consumptions=[]), "failed")
    assert not EmailLog.objects.exists()
    assert set(NotificationDeliveryLog.objects.values_list("feature", flat=True)) == {"machine_service"}


def test_actual_type_and_machine_room_scope_changes_after_assignment(
    history_lab, providers, django_capture_on_commit_callbacks,
):
    lab = history_lab
    typed = room(lab.space, "Type", "-100201")
    machine = room(lab.space, "Machine", "-100202")
    foreign = room(lab.space, "Foreign type", "-100203")
    room(lab.other_space, "Other tenant", "-100204")
    other_type = MachineType.objects.create(makerspace=lab.space, slug="mill", name="Mill")
    DestinationMachineTypeScope.objects.create(destination=typed, machine_type=lab.kind)
    DestinationMachineScope.objects.create(destination=machine, machine=lab.machine)
    DestinationMachineTypeScope.objects.create(destination=foreign, machine_type=other_type)
    with django_capture_on_commit_callbacks(execute=True):
        row = submit_service(lab)
    assert [call["chat_id"] for call in providers] == ["-100201"]
    with django_capture_on_commit_callbacks(execute=True):
        row = accept(row, lab.user)
    assert [call["chat_id"] for call in providers] == ["-100201", "-100201"]
    with django_capture_on_commit_callbacks(execute=True):
        start(row, lab.user, role_scope.EXEMPT, machine_id=lab.machine.pk)
    assert sorted(call["chat_id"] for call in providers[2:]) == ["-100201", "-100202"]
    assert NotificationDeliveryLog.objects.filter(event="started", status="sent").count() == 2
    assert not NotificationDeliveryLog.objects.filter(destination=foreign).exists()
    assert not NotificationDeliveryLog.objects.filter(makerspace=lab.other_space).exists()


def test_real_rollback_and_invalid_replay_add_no_notifications(
    history_lab, providers, django_capture_on_commit_callbacks,
):
    lab = history_lab
    lab.space.telegram_group_chat_id = "-100301"
    lab.space.save(update_fields=["telegram_group_chat_id"])
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError, match="rollback"):
            with transaction.atomic():
                submit_service(lab)
                assert not Notification.objects.exists() and not providers
                raise RuntimeError("rollback")
    assert not MachineServiceRequest.objects.exists()
    assert not Notification.objects.exists() and not NotificationDeliveryLog.objects.exists()
    assert not AuditLog.objects.filter(action="machine_service.submitted").exists()
    assert providers == []
    with django_capture_on_commit_callbacks(execute=True):
        row = submit_service(lab)
        row = accept(row, lab.user)
    before = (Notification.objects.count(), NotificationDeliveryLog.objects.count(), len(providers))
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(ServiceInvalidTransition):
            accept(row, lab.user)
    assert before == (Notification.objects.count(), NotificationDeliveryLog.objects.count(), len(providers))


def test_outbound_failure_keeps_committed_workflow_and_audit(
    history_lab, monkeypatch, django_capture_on_commit_callbacks,
):
    lab = history_lab
    lab.space.telegram_group_chat_id = "-100401"
    lab.space.save(update_fields=["telegram_group_chat_id"])

    def unavailable(*args, **kwargs):
        raise OSError("Synthetic transport unavailable")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    with django_capture_on_commit_callbacks(execute=True):
        row = submit_service(lab)
    row.refresh_from_db()
    assert row.status == "pending"
    assert AuditLog.objects.filter(action="machine_service.submitted", target_id=str(row.pk)).count() == 1
    assert Notification.objects.filter(event="machine_service.submitted").count() == 1
    log = NotificationDeliveryLog.objects.get()
    assert log.status == "failed" and log.attempts == 1
