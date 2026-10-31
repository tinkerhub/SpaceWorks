"""Managed mail reserves once; quota refusals never become tomorrow's backlog."""

from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.mail import EmailMultiAlternatives

from apps.audit.models import AuditLog
from apps.integrations import dispatch, services, tasks
from apps.integrations.management.commands.flush_email_outbox import Command
from apps.integrations.models import DailyEmailCounter, EmailLog
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

DENIAL = "daily_email_limit_reached"
OLD_DENIAL = "Daily email limit reached for this space."


@pytest.fixture
def managed_mail(monkeypatch):
    space = make_space("email-quota-terminal-fix")
    clock = {"now": datetime(2026, 10, 20, 12, tzinfo=dt_timezone.utc), "cap": 1}
    monkeypatch.setattr("django.utils.timezone.now", lambda: clock["now"])
    monkeypatch.setattr("apps.makerspaces.domain_verification.is_self_host", lambda: False)
    monkeypatch.setattr("apps.makerspaces.limits.resource_limit", lambda *_: clock["cap"])
    monkeypatch.setattr(
        "apps.integrations.email.makerspace_mail_connection",
        lambda *_: (None, "sender@example.test"),
    )
    send = Mock(return_value=1)
    enqueue = Mock()
    monkeypatch.setattr(EmailMultiAlternatives, "send", send)
    monkeypatch.setattr(tasks.deliver_email_task, "delay", enqueue)
    monkeypatch.setattr(tasks, "record_worker_heartbeat", Mock())
    monkeypatch.setattr("apps.notifications.emit.emit_notification", Mock())
    return space, clock, send, enqueue


def send_mail(space, *, sync=False):
    return dispatch.dispatch_email(
        makerspace=space, to_email="member@example.test", subject="Quota boundary",
        text_body="Stored retry content", sync=sync,
    )


def assert_refused(log):
    log.refresh_from_db()
    assert log.status == EmailLog.Status.SKIPPED
    assert log.error == DENIAL
    assert log.attempts == 0
    assert log.sent_at is None


def test_zero_cap_records_terminal_skip_without_send_enqueue_or_reservation(
    managed_mail, django_capture_on_commit_callbacks,
):
    space, clock, send, enqueue = managed_mail
    clock["cap"] = 0
    with django_capture_on_commit_callbacks(execute=True):
        queued = send_mail(space)
        synchronous = send_mail(space, sync=True)
    for log in (queued, synchronous):
        assert_refused(log)
    assert DailyEmailCounter.objects.get(makerspace=space, day=clock["now"].date()).count == 0
    send.assert_not_called()
    enqueue.assert_not_called()


@pytest.mark.parametrize("sync", [True, False], ids=["synchronous", "queued"])
def test_one_cap_allows_first_send_or_reservation_and_terminally_skips_second(
    managed_mail, django_capture_on_commit_callbacks, sync,
):
    space, clock, send, enqueue = managed_mail
    with django_capture_on_commit_callbacks(execute=True):
        first = send_mail(space, sync=sync)
        second = send_mail(space, sync=sync)
    assert_refused(second)
    assert DailyEmailCounter.objects.get(makerspace=space, day=clock["now"].date()).count == 1
    if not sync:
        enqueue.assert_called_once_with(first.pk)
        send.assert_not_called()
        tasks.deliver_email_task(first.pk)
        tasks.deliver_email_task(first.pk)
    else:
        enqueue.assert_not_called()
    first.refresh_from_db()
    assert first.status == EmailLog.Status.SENT
    assert first.attempts == 1
    assert first.error == ""
    assert first.sent_at is not None
    assert send.call_count == 1


def test_retry_and_next_day_flush_refuse_new_skip_and_exact_legacy_cap_failure(
    managed_mail, django_capture_on_commit_callbacks,
):
    space, clock, send, enqueue = managed_mail
    clock["cap"] = 0
    refused = send_mail(space)
    legacy = EmailLog.objects.create(
        makerspace=space, to_email="member@example.test", subject="Old refusal",
        text_body="Stored retry content", status=EmailLog.Status.FAILED, error=OLD_DENIAL,
    )
    clock["now"] += timedelta(days=1)
    clock["cap"] = 1
    before = AuditLog.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        for log in (refused, legacy):
            with pytest.raises(services.EmailRetryError):
                services.retry_email_log(None, log)
        # Exercise the command's real selection/retry service without invoking manage.py.
        command = Command(stdout=StringIO())
        command.handle(max_age_hours=48, limit=100)
    assert_refused(refused)
    legacy.refresh_from_db()
    assert legacy.status == EmailLog.Status.FAILED
    assert legacy.error == OLD_DENIAL
    assert legacy.attempts == 0
    assert legacy.sent_at is None
    assert "retried 0, skipped 1" in command.stdout.getvalue()
    send.assert_not_called()
    enqueue.assert_not_called()
    assert AuditLog.objects.count() == before
    assert list(DailyEmailCounter.objects.values_list("count", flat=True)) == [0]


@pytest.mark.parametrize("entry", ["task", "direct"])
@pytest.mark.parametrize("legacy", [False, True], ids=["skipped", "legacy-failed"])
def test_duplicate_delivery_cannot_revive_quota_denial_next_day(
    managed_mail, entry, legacy,
):
    space, clock, send, enqueue = managed_mail
    clock["cap"] = 0
    log = send_mail(space)
    if legacy:
        log.status = EmailLog.Status.FAILED
        log.error = OLD_DENIAL
        log.save(update_fields=["status", "error"])
    clock["now"] += timedelta(days=1)
    clock["cap"] = 1
    for _ in range(2):
        if entry == "task":
            tasks.deliver_email_task(log.pk)
        else:
            dispatch._deliver(EmailLog.objects.get(pk=log.pk))
    assert_refused(log)
    send.assert_not_called()
    enqueue.assert_not_called()
    assert list(DailyEmailCounter.objects.values_list("count", flat=True)) == [0]


def test_new_next_day_message_can_reserve_quota_while_yesterdays_skip_stays_terminal(
    managed_mail,
):
    space, clock, send, enqueue = managed_mail
    first = send_mail(space, sync=True)
    refused = send_mail(space, sync=True)
    yesterday = clock["now"].date()
    clock["now"] += timedelta(days=1)
    fresh = send_mail(space, sync=True)
    assert first.status == fresh.status == EmailLog.Status.SENT
    assert_refused(refused)
    assert DailyEmailCounter.objects.get(day=yesterday, makerspace=space).count == 1
    assert DailyEmailCounter.objects.get(day=clock["now"].date(), makerspace=space).count == 1
    assert send.call_count == 2
    enqueue.assert_not_called()


@pytest.mark.parametrize("retry_days", [0, 1], ids=["same-day", "next-day"])
def test_provider_failure_retries_reserved_message_without_a_second_quota_slot(
    managed_mail, django_capture_on_commit_callbacks, retry_days,
):
    space, clock, send, enqueue = managed_mail
    send.side_effect = RuntimeError("transport unavailable")
    log = send_mail(space, sync=True)
    assert log.status == EmailLog.Status.FAILED
    assert log.error == "email_delivery_failed:RuntimeError"
    assert log.attempts == 1
    assert log.sent_at is None
    assert DailyEmailCounter.objects.get(makerspace=space).count == 1
    send.side_effect = None
    clock["now"] += timedelta(days=retry_days)
    with django_capture_on_commit_callbacks(execute=True):
        services.retry_email_log(None, log)
    enqueue.assert_called_once_with(log.pk)
    tasks.deliver_email_task(log.pk)
    tasks.deliver_email_task(log.pk)
    log.refresh_from_db()
    assert log.status == EmailLog.Status.SENT
    assert log.error == ""
    assert log.attempts == 2
    assert log.sent_at is not None
    assert send.call_count == 2
    assert list(DailyEmailCounter.objects.values_list("count", flat=True)) == [1]
