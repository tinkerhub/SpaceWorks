"""Executable private Celery worker for the isolated Stage3 broker proof.

Run only via test_recovery_live_generation.py; this imports the actual task fence.
"""

from contextlib import ExitStack
import os
import sys


def create_app(generation, prefix):
    import django
    django.setup()
    from celery import Celery
    from django.conf import settings
    from config.task_queue_settings import default_task_queue

    url = os.environ.get("SPACEWORKS_TEST_REDIS_URL")
    assert url, "Dedicated SPACEWORKS_TEST_REDIS_URL required; never use CELERY_BROKER_URL fallback."
    app = Celery("recovery-stage3", set_as_current=False,
        task_cls="apps.tenant_migration.task_gate:TenantGateTask")
    with ExitStack() as cleanup:
        cleanup.callback(app.close)
        # Freeze the actual Django Celery settings once. The pytest autouse eager
        # override must not outrank this proof's explicit live transport settings via
        # namespaced aliases; each private app has its own normal lowercase config.
        app.conf.update({name.removeprefix("CELERY_").lower(): getattr(settings, name)
            for name in dir(settings) if name.startswith("CELERY_")})
        queue = default_task_queue(generation)
        app.conf.update(broker_url=url, broker_read_url=url, broker_write_url=url,
            result_backend=url, task_always_eager=False,
            task_default_queue=queue, task_default_exchange=queue, task_default_routing_key=queue,
            task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
            task_serializer="json", result_serializer="json", accept_content=["json"],
            broker_transport_options={"global_keyprefix": prefix, "visibility_timeout": 15},
            result_backend_transport_options={"global_keyprefix": prefix + "results:"})
        assert app.conf.task_always_eager is False
        assert app.conf.broker_url == app.conf.broker_read_url == app.conf.broker_write_url == app.conf.result_backend == url
        assert (app.conf.task_default_queue, app.conf.task_default_exchange,
            app.conf.task_default_routing_key) == (queue, queue, queue)

        @app.task(bind=True, shared=False, name="spaceworks.stage3.recovery.observe", max_retries=2)
        def observe(self, row_id, mode):
            import redis
            from django.db import transaction
            from django.db.models import F
            from apps.integrations.models import EmailLog

            broker = redis.Redis.from_url(url)
            try:
                if mode == "old-retry" and self.request.retries == 0:
                    broker.set(prefix + "old-retry-published", self.request.id)
                    raise self.retry(countdown=180)
                if mode == "old-unacked" and broker.setnx(prefix + "unacked-entered", self.request.id):
                    broker.blpop(prefix + "never-released", timeout=300)
                    # The first worker is killed here. A redelivery must be capable
                    # of touching the reused row, so it falls through on re-entry;
                    # only generation isolation may keep it away from replacement SQL.
                if mode == "new-retry" and self.request.retries == 0:
                    raise self.retry(countdown=1)
                with transaction.atomic():
                    row = EmailLog.objects.select_for_update().get(pk=row_id)
                    identity = row.subject
                    EmailLog.objects.filter(pk=row_id).update(attempts=F("attempts") + 1, event=mode)
                broker.rpush(prefix + "effects", mode + ":" + identity)
                return {"row_id": row_id, "identity": identity, "mode": mode,
                    "queue": self.request.delivery_info.get("routing_key")}
            finally:
                broker.close()
        cleanup.pop_all()
    return app, observe


def main():
    from celery.signals import worker_ready
    from django.conf import settings
    import redis

    generation = os.environ["SPACEWORKS_TASK_GENERATION"]
    prefix = os.environ["SPACEWORKS_TEST_REDIS_PREFIX"]
    app, _task = create_app(generation, prefix)
    expected = "spaceworks-" + generation
    assert (settings.CELERY_TASK_DEFAULT_QUEUE, settings.CELERY_TASK_DEFAULT_EXCHANGE,
        settings.CELERY_TASK_DEFAULT_ROUTING_KEY) == (expected, expected, expected)

    @worker_ready.connect(weak=False)
    def ready(**_kwargs):
        broker = redis.Redis.from_url(os.environ["SPACEWORKS_TEST_REDIS_URL"])
        broker.set(prefix + "ready:" + generation, expected)
        broker.close()

    app.worker_main(["worker", "--pool=solo", "--concurrency=1", "--without-gossip", "--without-mingle",
        "--without-heartbeat", "--loglevel=WARNING", "--hostname=recovery-" + generation + "@%h"])


if __name__ == "__main__":
    assert sys.argv[1:] == ["worker"], "Use python -B -m tests.backup.recovery_live_tasks worker"
    main()
