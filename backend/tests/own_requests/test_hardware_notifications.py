"""Staff inbox changes follow actual hardware workflows and transaction outcomes."""

import pytest
from django.db import transaction

from apps.audit.models import AuditLog
from apps.hardware_requests.notifications import notify_return_due
from apps.hardware_requests.workflow import (
    accept_request, cancel_request, issue_request, reject_request, return_items,
)
from apps.integrations.models import NotificationDeliveryLog
from apps.notifications.models import Notification
from tests.inventory_lending_evidence_helpers import photo, uploaded_images
from tests.own_requests.own_requests_support import (
    history_lab, providers, submit_hardware,
)
from tests.return_helpers import make_member

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("outcome", ["returned", "closed_with_issue", "rejected", "cancelled"])
def test_hardware_each_workflow_transition_emits_one_safe_staff_row(
    history_lab, providers, monkeypatch, settings, django_capture_on_commit_callbacks, outcome,
):
    lab = history_lab
    lab.actor = make_member("hardware-notification-manager", lab.space)
    lab.space.telegram_group_chat_id = "-100501"
    lab.space.save(update_fields=["telegram_group_chat_id"])
    store = uploaded_images(monkeypatch, settings)
    events = []

    def commit(operation, event):
        before = Notification.objects.count()
        with django_capture_on_commit_callbacks(execute=True):
            row = operation()
        assert Notification.objects.count() == before + 1
        inbox = Notification.objects.latest("pk")
        assert inbox.event == f"request.{event}"
        assert inbox.url_path == f"/m/{lab.space.slug}/admin/requests"
        assert inbox.body == f"Hardware request #{row.pk} {event}."
        for value in ("Private borrower", "private-borrower@example.test", "+15550123456",
                      "Private cancellation", str(row.public_token)):
            assert value not in inbox.body
        events.append(f"request.{event}")
        return row

    row = commit(lambda: submit_hardware(lab), "submitted")
    if outcome == "rejected":
        row = commit(lambda: reject_request(lab.actor, row, "Private rejection"), "rejected")
    else:
        item = row.items.get()
        row = commit(lambda: accept_request(lab.actor, row, {item.pk: 2}), "accepted")
        if outcome == "cancelled":
            row = commit(lambda: cancel_request(lab.actor, row, "Private cancellation"), "cancelled")
        else:
            issue_photo = photo(lab, store, "issue")
            row = commit(lambda: issue_request(lab.actor, row, issue_photo.pk), "issued")
            returned = photo(lab, store, "return")
            row = commit(lambda: return_items(lab.actor, row, returned.pk, "First return", None, [{
                "item_id": item.pk, "returned": 1, "damaged": 0, "missing": 0,
            }]), "partially_returned")
            final_photo = photo(lab, store, "return")
            row = commit(lambda: return_items(lab.actor, row, final_photo.pk, "Final return", None, [{
                "item_id": item.pk, "returned": int(outcome == "returned"),
                "damaged": int(outcome == "closed_with_issue"), "missing": 0,
            }]), outcome)
    row.refresh_from_db()
    assert row.status == outcome
    assert list(Notification.objects.order_by("pk").values_list("event", flat=True)) == events
    assert len(providers) == len(events)
    assert NotificationDeliveryLog.objects.filter(feature="hardware_requests", status="sent").count() == len(events)
    assert AuditLog.objects.filter(target_id=str(row.pk), action=f"request.{outcome}").count() == 1


def test_hardware_rollback_and_actual_idempotent_submit_have_no_extra_alert(
    history_lab, providers, django_capture_on_commit_callbacks,
):
    lab = history_lab
    lab.space.telegram_group_chat_id = "-100601"
    lab.space.save(update_fields=["telegram_group_chat_id"])
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError, match="rollback"):
            with transaction.atomic():
                submit_hardware(lab, anonymous=True)
                assert not Notification.objects.exists() and not providers
                raise RuntimeError("rollback")
    assert not lab.space.hardware_requests.exists()
    assert not Notification.objects.exists() and not NotificationDeliveryLog.objects.exists()
    assert not AuditLog.objects.filter(action="request.submitted").exists()
    assert providers == []
    with django_capture_on_commit_callbacks(execute=True):
        original = submit_hardware(lab, anonymous=True)
    before = (Notification.objects.count(), NotificationDeliveryLog.objects.count(), len(providers))
    with django_capture_on_commit_callbacks(execute=True):
        replay = submit_hardware(lab, anonymous=True)
    assert replay.pk == original.pk
    assert before == (Notification.objects.count(), NotificationDeliveryLog.objects.count(), len(providers))
    assert before == (1, 1, 1)
    assert AuditLog.objects.filter(action="request.submitted").count() == 1


def test_return_reminder_keeps_channel_counts_without_new_staff_inbox_event(history_lab, providers):
    lab = history_lab
    lab.space.telegram_group_chat_id = "-100701"
    lab.space.save(update_fields=["telegram_group_chat_id"])
    # Build an issued row, as the periodic reminder task receives it.
    from tests.own_requests.own_requests_support import hardware

    row = hardware(lab, status="issued")
    assert notify_return_due(row) is True
    assert Notification.objects.count() == 0
    log = NotificationDeliveryLog.objects.get()
    assert (log.feature, log.event, log.status) == ("hardware_requests", "return_reminder", "sent")
    assert len(providers) == 1


def test_hardware_provider_failure_preserves_submission_and_audit(
    history_lab, monkeypatch, django_capture_on_commit_callbacks,
):
    lab = history_lab
    lab.space.telegram_group_chat_id = "-101101"
    lab.space.save(update_fields=["telegram_group_chat_id"])

    def unavailable(*args, **kwargs):
        raise OSError("Synthetic transport unavailable")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    with django_capture_on_commit_callbacks(execute=True):
        row = submit_hardware(lab)
    row.refresh_from_db()
    assert row.status == "pending_approval"
    assert AuditLog.objects.filter(action="request.submitted", target_id=str(row.pk)).count() == 1
    assert Notification.objects.filter(event="request.submitted").count() == 1
    log = NotificationDeliveryLog.objects.get()
    assert log.status == "failed" and log.attempts == 1
