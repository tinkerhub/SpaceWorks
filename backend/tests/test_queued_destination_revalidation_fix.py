"""Queued chat deliveries honor the room's current activation and scope."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.integrations import tasks
from apps.integrations.destinations import NotificationScope
from apps.integrations.dispatch_channels import _deliver_notification, dispatch_channel
from apps.integrations.models import NotificationDeliveryLog, NotificationDeliveryStatus as Status
from apps.integrations.models_destinations import NotificationDestination
from tests.test_notification_destinations import (
    make_machine,
    make_space,
    telegram_destination,
    webhook_destination,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def queued_room(monkeypatch, django_capture_on_commit_callbacks):
    webhook, telegram, push, enqueue, quota = (Mock(return_value=True) for _ in range(5))
    monkeypatch.setattr("apps.integrations.webhooks.send_webhook", webhook)
    monkeypatch.setattr("apps.integrations.telegram.send_message", telegram)
    monkeypatch.setattr("apps.integrations.push.deliver_native_push", push)
    monkeypatch.setattr("apps.integrations.push.push_configured", lambda: True)
    monkeypatch.setattr(tasks.deliver_notification_task, "delay", enqueue)
    monkeypatch.setattr(tasks, "record_worker_heartbeat", Mock())
    monkeypatch.setattr("apps.makerspaces.limits.reserve_notification_quota", quota)

    def queue(channel, *, room_kind="scoped"):
        space = make_space("queued-destination-revalidation")
        # Keep a working legacy credential underneath the room to detect fallback.
        space.set_slack_webhook_url("https://hooks.example.test/legacy")
        space.set_telegram_bot_token("space-token")
        space.telegram_group_chat_id = "-100111"
        space.save()
        machine = make_machine(space, "laser")
        room = None
        if room_kind != "legacy":
            room = (
                telegram_destination(space, "Workshop", "-100222")
                if channel == "telegram" else webhook_destination(space, "slack", "Workshop")
            )
            if room_kind == "scoped":
                room.machine_scopes.create(machine=machine)
        with django_capture_on_commit_callbacks(execute=True):
            [log] = dispatch_channel(
                makerspace=space, channel=channel, feature="maintenance", event="logged",
                text_body="Machine requires attention", payload={"marker": "preserved"},
                scope=NotificationScope(machine=machine), sync=False,
            )
        enqueue.assert_called_once_with(log.pk)
        assert log.status == Status.PENDING
        assert log.payload == {"marker": "preserved", "scope": {
            "machine_id": machine.pk, "machine_type_id": machine.machine_type_id,
            "category_id": None,
        }}
        return SimpleNamespace(
            space=space, room=room, machine=machine, log=log, webhook=webhook,
            telegram=telegram, push=push, quota=quota, enqueue=enqueue,
        )
    return queue


def stale_log(log):
    return NotificationDeliveryLog.objects.select_related("destination").prefetch_related(
        "destination__machine_scopes", "destination__machine_type_scopes",
        "destination__category_scopes",
    ).get(pk=log.pk)


def withdraw(ctx, change):
    if change == "disabled":
        NotificationDestination.objects.filter(pk=ctx.room.pk).update(is_active=False)
    else:
        other = make_machine(ctx.space, "printer")
        ctx.room.machine_scopes.all().delete()
        ctx.room.machine_scopes.create(machine=other)


def restore(ctx):
    NotificationDestination.objects.filter(pk=ctx.room.pk).update(is_active=True)
    ctx.room.machine_scopes.all().delete()
    ctx.room.machine_scopes.create(machine=ctx.machine)


def assert_no_sends(ctx):
    ctx.webhook.assert_not_called()
    ctx.telegram.assert_not_called()
    ctx.push.assert_not_called()


@pytest.mark.parametrize("channel", ["slack", "telegram"])
@pytest.mark.parametrize("change", ["disabled", "scope_withdrawn"])
def test_stale_queued_room_and_prefetched_scopes_are_reloaded_before_delivery(
    queued_room, channel, change,
):
    ctx = queued_room(channel)
    stale = stale_log(ctx.log)
    assert stale.destination.is_active
    assert [link.machine_id for link in stale.destination.machine_scopes.all()] == [ctx.machine.pk]
    withdraw(ctx, change)
    # Demonstrate the test really passes stale cached FK and scope data to delivery.
    assert stale.destination.is_active
    assert [link.machine_id for link in stale.destination.machine_scopes.all()] == [ctx.machine.pk]

    _deliver_notification(stale)

    ctx.log.refresh_from_db()
    assert ctx.log.status == Status.SKIPPED
    assert ctx.log.error == f"notification_destination_{change}"
    assert ctx.log.attempts == 0
    assert ctx.log.sent_at is None
    assert_no_sends(ctx)
    ctx.quota.assert_called_once_with(ctx.space, channel)
    restore(ctx)
    tasks.deliver_notification_task(ctx.log.pk)
    tasks.deliver_notification_task(ctx.log.pk)
    _deliver_notification(NotificationDeliveryLog.objects.get(pk=ctx.log.pk))
    ctx.log.refresh_from_db()
    assert ctx.log.status == Status.SKIPPED
    assert ctx.log.error == f"notification_destination_{change}"
    assert ctx.log.attempts == 0
    assert_no_sends(ctx)


@pytest.mark.parametrize("channel", ["slack", "telegram"])
@pytest.mark.parametrize("change", ["disabled", "scope_withdrawn"])
def test_worker_retry_rechecks_room_after_a_real_provider_failure(queued_room, channel, change):
    ctx = queued_room(channel)
    sender = ctx.telegram if channel == "telegram" else ctx.webhook
    sender.side_effect = RuntimeError("provider unavailable")
    _deliver_notification(ctx.log)
    ctx.log.refresh_from_db()
    assert ctx.log.status == Status.FAILED
    assert ctx.log.error == "notification_delivery_failed:RuntimeError"
    assert ctx.log.attempts == 1
    assert ctx.log.sent_at is None
    sender.assert_called_once()
    assert sender.call_args.kwargs["destination"].pk == ctx.room.pk
    sender.reset_mock(side_effect=True)
    sender.return_value = True
    withdraw(ctx, change)

    tasks.deliver_notification_task(ctx.log.pk)

    ctx.log.refresh_from_db()
    assert ctx.log.status == Status.SKIPPED
    assert ctx.log.error == f"notification_destination_{change}"
    assert ctx.log.attempts == 1  # Policy refusal is not a second provider attempt.
    assert ctx.log.sent_at is None
    assert_no_sends(ctx)
    restore(ctx)
    tasks.deliver_notification_task(ctx.log.pk)
    ctx.log.refresh_from_db()
    assert ctx.log.status == Status.SKIPPED
    assert ctx.log.error == f"notification_destination_{change}"
    assert ctx.log.attempts == 1
    assert_no_sends(ctx)
    ctx.quota.assert_called_once_with(ctx.space, channel)


@pytest.mark.parametrize("channel", ["slack", "telegram"])
@pytest.mark.parametrize("room_kind", ["scoped", "unscoped"])
def test_current_matching_or_unscoped_room_delivers_once(queued_room, channel, room_kind):
    ctx = queued_room(channel, room_kind=room_kind)
    tasks.deliver_notification_task(ctx.log.pk)
    tasks.deliver_notification_task(ctx.log.pk)
    ctx.log.refresh_from_db()
    assert ctx.log.status == Status.SENT
    assert ctx.log.error == ""
    assert ctx.log.attempts == 1
    assert ctx.log.sent_at is not None
    sender = ctx.telegram if channel == "telegram" else ctx.webhook
    other = ctx.webhook if channel == "telegram" else ctx.telegram
    sender.assert_called_once()
    assert sender.call_args.kwargs["destination"].pk == ctx.room.pk
    other.assert_not_called()
    ctx.push.assert_not_called()
    ctx.quota.assert_called_once_with(ctx.space, channel)


@pytest.mark.parametrize("channel", ["slack", "telegram"])
@pytest.mark.parametrize("cached", [False, True], ids=["fresh", "cached"])
def test_deleted_queued_room_preserves_failed_history_without_legacy_fallback(
    queued_room, channel, cached,
):
    ctx = queued_room(channel)
    snapshot = stale_log(ctx.log) if cached else None
    ctx.room.delete()
    log = snapshot or NotificationDeliveryLog.objects.get(pk=ctx.log.pk)
    _deliver_notification(log)
    ctx.log.refresh_from_db()
    assert ctx.log.destination_id is None
    assert ctx.log.destination_label == "Workshop"
    assert ctx.log.status == Status.FAILED
    assert ctx.log.error == "notification_destination_deleted"
    assert ctx.log.attempts == 1
    assert ctx.log.sent_at is None
    assert_no_sends(ctx)


@pytest.mark.parametrize("channel", ["slack", "telegram", "native_push"])
def test_null_destination_legacy_and_native_push_delivery_are_unaffected(queued_room, channel):
    ctx = queued_room(channel, room_kind="legacy")
    tasks.deliver_notification_task(ctx.log.pk)
    ctx.log.refresh_from_db()
    assert ctx.log.destination_id is None
    assert ctx.log.destination_label == ""
    assert ctx.log.status == Status.SENT
    assert ctx.log.error == ""
    assert ctx.log.attempts == 1
    assert ctx.log.sent_at is not None
    if channel == "native_push":
        ctx.push.assert_called_once()
        assert ctx.push.call_args.args[0].payload["scope"]["machine_id"] == ctx.machine.pk
        ctx.webhook.assert_not_called()
        ctx.telegram.assert_not_called()
    else:
        sender = ctx.telegram if channel == "telegram" else ctx.webhook
        sender.assert_called_once()
        assert sender.call_args.kwargs["destination"] is None
        ctx.push.assert_not_called()
