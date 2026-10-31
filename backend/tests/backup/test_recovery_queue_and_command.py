"""Queue identity and real management parser contract; no broker connection."""

from io import StringIO
import uuid

import pytest
from celery import Celery
from celery.beat import ScheduleEntry, Scheduler
from celery.exceptions import Retry
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import CommandError

from apps.backup.host_restore_configuration import CONTINUITY, merged_environment
from apps.backup.management.commands.preflight_backup_import import Command
from config.task_queue_settings import default_task_queue


GENERATION = "12345678-1234-4abc-8abc-123456789abc"


@pytest.mark.parametrize("bad", [None, " ", "bad", GENERATION.upper(), "{" + GENERATION + "}", GENERATION.replace("-", ""), 1])
def test_only_canonical_uuid_or_blank_generation_is_accepted(bad):
    with pytest.raises(ImproperlyConfigured):
        default_task_queue(bad)


def test_generation_changes_default_publication_retry_and_beat_routing():
    assert default_task_queue("") == "celery"
    queue = default_task_queue(GENERATION)
    assert queue == "spaceworks-" + GENERATION
    app = Celery("recovery-routing", broker="memory://", backend="cache+memory://")
    app.conf.update(task_default_queue=queue, task_default_exchange=queue,
        task_default_routing_key=queue, task_always_eager=False)
    try:
        @app.task(bind=True, name="recovery.route")
        def task(self):
            self.retry(countdown=3)
        route = app.amqp.router.route({}, task.name, (), {})
        assert route["queue"].name == queue
        assert route["queue"].exchange.name == queue and route["queue"].routing_key == queue
        task.push_request(id=str(uuid.uuid4()), called_directly=False, is_eager=False, retries=0,
                delivery_info={"exchange": queue, "routing_key": queue})
        try:
            signature = task.signature_from_request()
            assert signature.options["exchange"] == queue and signature.options["routing_key"] == queue
            with pytest.raises(Retry):
                task.retry(countdown=0)
        finally:
            task.pop_request()
        entry = ScheduleEntry(name="periodic", task=task.name, schedule=10, app=app)
        result = Scheduler(app=app, lazy=True).apply_async(entry)
        assert result.id
        with app.connection_for_read() as connection:
            simple = connection.SimpleQueue(queue)
            messages = [simple.get(block=False), simple.get(block=False)]
            assert {message.headers["retries"] for message in messages} == {0, 1}
            for message in messages:
                assert message.headers["task"] == task.name
                assert message.delivery_info["routing_key"] == queue
                message.ack()
            simple.close()
    finally:
        app.close()


def test_source_continuity_cannot_adopt_a_task_generation(monkeypatch):
    from apps.backup.archive_metadata import settings_manifest
    monkeypatch.setenv("SPACEWORKS_TASK_GENERATION", GENERATION)
    assert "SPACEWORKS_TASK_GENERATION" not in settings_manifest()
    continuity = {name: "source-value-" + name for name in CONTINUITY}
    old = b"TARGET_ONLY='keep'\nSPACEWORKS_TASK_GENERATION='old-value'\n"
    merged = merged_environment(old, continuity, GENERATION)
    assert b"TARGET_ONLY='keep'" in merged
    assert ("SPACEWORKS_TASK_GENERATION='" + GENERATION + "'").encode() in merged
    continuity["SPACEWORKS_TASK_GENERATION"] = "source-queue"
    from apps.backup.host_restore_transport import RestoreHostError
    with pytest.raises(RestoreHostError, match="allowlist"):
        merged_environment(old, continuity, GENERATION)


@pytest.mark.parametrize("supplied", [None, "{4511B438-1234-4C35-89AB-0123456789AB}"])
def test_actual_optional_uuid_parser_forwards_canonical_typed_uuid(monkeypatch, supplied):
    command = Command(stdout=StringIO())
    parser = command.create_parser("manage.py", "preflight_backup_import")
    argv = ["--encrypted-file", "outer", "--bundle", "tar", "--manifest", "manifest", "--continuity-secrets", "keys"]
    if supplied:
        argv += ["--restore-id", supplied]
    options = vars(parser.parse_args(argv))
    assert options["restore_id"] is None or isinstance(options["restore_id"], uuid.UUID)
    seen = []
    monkeypatch.setattr("apps.backup.management.commands.preflight_backup_import.validate_import_preflight",
        lambda **kwargs: seen.append(kwargs))
    command.handle(**options)
    expected = str(uuid.UUID(supplied)) if supplied else None
    assert seen[0]["restore_id"] == expected


def test_invalid_restore_uuid_is_rejected_by_parser_before_validator():
    parser = Command().create_parser("manage.py", "preflight_backup_import")
    with pytest.raises(CommandError):
        parser.parse_args(["--encrypted-file", "x", "--bundle", "x", "--manifest", "x",
            "--continuity-secrets", "x", "--restore-id", "invalid"])
