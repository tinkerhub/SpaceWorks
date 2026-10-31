"""SLOW explicit lane: real Redis/Celery processes + committed replacement SQL row.

Requires SPACEWORKS_TEST_REDIS_URL, SPACEWORKS_TEST_REDIS_DEDICATED=1,
SPACEWORKS_TEST_LIVE_DB_NAME=<actual pytest DB>, full repo mount, TCP PG and
permission to start/kill two private solo workers. Never run with ordinary focus.
Old broker data is deliberately retained under the printed private evidence prefix.
"""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest
import redis
from celery import _state as celery_state
from celery.beat import ScheduleEntry, Scheduler
from django.db import connection, transaction

from apps.backup.models import DeploymentRecoveryState
from apps.integrations.models import EmailLog
from tests.backup.recovery_live_support import dedicated_url, retained_message_ids, stop_worker, wait_until, worker
from tests.backup.recovery_live_tasks import create_app


pytestmark = pytest.mark.django_db(transaction=True)


def test_real_old_queued_unacked_retry_eta_ids_never_execute_on_replacement_rows(tmp_path, monkeypatch):
    url = dedicated_url()
    for name in ("CELERY_BROKER_URL", "CELERY_BROKER_READ_URL",
                 "CELERY_BROKER_WRITE_URL", "CELERY_RESULT_BACKEND"):
        monkeypatch.setenv(name, url)
    current = celery_state.get_current_app()
    default = celery_state.default_app
    prefix = "spaceworks-stage3:" + uuid.uuid4().hex + ":"
    with ExitStack() as cleanup:
        broker = redis.Redis.from_url(url)
        cleanup.callback(broker.close)
        broker.ping()
        assert not list(broker.scan_iter(match=prefix + "*"))
        old_generation, new_generation = str(uuid.uuid4()), str(uuid.uuid4())
        old_app, old_task = create_app(old_generation, prefix)
        cleanup.callback(old_app.close)
        new_app, new_task = create_app(new_generation, prefix)
        cleanup.callback(new_app.close)
        assert celery_state.get_current_app() is current
        assert celery_state.default_app is default
        old_queue = "spaceworks-" + old_generation
        new_queue = "spaceworks-" + new_generation
        DeploymentRecoveryState.objects.filter(pk=1).update(mode="normal", active_restore=None)
        with transaction.atomic():
            original = EmailLog.objects.create(to_email="stage3@example.invalid", subject="OLD TARGET IDENTITY", connection_kind="platform")
        row_id = original.pk
        old_worker = worker(tmp_path, old_generation, prefix, url)
        cleanup.callback(stop_worker, old_worker)
        wait_until(lambda: broker.get(prefix + "ready:" + old_generation), reason="old worker readiness", process=old_worker)
        retry = old_task.apply_async(args=[row_id, "old-retry"])
        wait_until(lambda: broker.get(prefix + "old-retry-published"), reason="actual old retry", process=old_worker)
        eta = old_task.apply_async(args=[row_id, "old-eta"], eta=datetime.now(timezone.utc) + timedelta(seconds=180))
        held = old_task.apply_async(args=[row_id, "old-unacked"])
        wait_until(lambda: broker.get(prefix + "unacked-entered"), reason="actual late-ack task entry", process=old_worker)
        stop_worker(old_worker, kill=True)  # Genuine unacked delivery; never mocked acknowledgement.
        queued = old_task.apply_async(args=[row_id, "old-queued"])
        old_ids = {result.id for result in (retry, eta, held, queued)}
        wait_until(lambda: old_ids <= retained_message_ids(broker, prefix), reason="old queued/unacked/retry/ETA retention")

        DeploymentRecoveryState.objects.filter(pk=1).update(mode="quarantined")
        with transaction.atomic():
            original.delete()
            replacement = EmailLog.objects.create(id=row_id, to_email="stage3@example.invalid", subject="RESTORED SOURCE IDENTITY", connection_kind="platform")
        assert replacement.pk == row_id
        assert not connection.in_atomic_block
        new_worker = worker(tmp_path, new_generation, prefix, url)
        cleanup.callback(stop_worker, new_worker)
        wait_until(lambda: broker.get(prefix + "ready:" + new_generation), reason="new worker readiness", process=new_worker)
        blocked = new_task.apply_async(args=[row_id, "must-be-blocked"])
        wait_until(blocked.ready, reason="real deployment Task fence", process=new_worker)
        assert blocked.state == "FAILURE"
        assert "DeploymentRecoveryTaskBlocked" in type(blocked.result).__name__
        replacement.refresh_from_db()
        assert replacement.attempts == 0 and broker.llen(prefix + "effects") == 0

        DeploymentRecoveryState.objects.filter(pk=1).update(mode="normal")
        ordinary = new_task.apply_async(args=[row_id, "new-default"])
        retried = new_task.apply_async(args=[row_id, "new-retry"])
        scheduler = Scheduler(app=new_app, lazy=True)
        cleanup.callback(scheduler.close)
        beat = scheduler.apply_async(ScheduleEntry(name="stage3-generation", task=new_task.name,
            args=[row_id, "new-beat"], schedule=60, app=new_app))
        results = [ordinary, retried, new_app.AsyncResult(beat.id)]
        for result in results:
            value = result.get(timeout=30)
            assert value["row_id"] == row_id and value["identity"] == "RESTORED SOURCE IDENTITY"
            assert value["queue"] == new_queue
        replacement.refresh_from_db()
        assert replacement.attempts == 3
        effects = [value.decode() for value in broker.lrange(prefix + "effects", 0, -1)]
        assert set(effects) == {name + ":RESTORED SOURCE IDENTITY" for name in ("new-default", "new-retry", "new-beat")}
        assert old_ids <= retained_message_ids(broker, prefix)
        evidence = {"scope": "live queue isolation with committed reused EmailLog ID; synthetic generation switch, no host restore",
            "prefix": prefix, "old_queue": old_queue, "new_queue": new_queue, "old_ids": sorted(old_ids),
            "retained_old_ids": sorted(old_ids & retained_message_ids(broker, prefix)), "row_id": row_id,
            "effects": effects, "old_queue_data_purged": False}
        (tmp_path / "live-generation-proof.json").write_text(json.dumps(evidence, indent=2) + "\n")
    assert celery_state.get_current_app() is current
    assert celery_state.default_app is default
    # No FLUSH, purge, queue delete or old-message cleanup, even on failure.
