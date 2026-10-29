"""Real queue setup and submission must serialize in either order on PostgreSQL."""
import queue
import threading
import time

import pytest
from django.db import close_old_connections, connection, connections

from apps.audit.models import AuditLog
from apps.machines import service_public_queue, service_workflow_actions
from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue
from apps.machines.printer_capabilities import PRINTER_CONFIG
from apps.machines.service_errors import ServiceMachineUnavailable
from apps.machines.service_workflow import submit
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db(transaction=True)

PRINTER_PAYLOAD = {
    "requested_material": "PLA", "requested_color": "Blue", "quantity": 1,
}


def _wait_until_blocked(waiter_pid, blocker_pid):
    deadline = time.monotonic() + 5
    poll = threading.Event()
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT %s = ANY(pg_blocking_pids(%s))", [blocker_pid, waiter_pid],
            )
            if cursor.fetchone()[0]:
                return
        # Poll the actual lock graph; elapsed time never establishes ordering.
        poll.wait(0.01)
    raise AssertionError("Competing workflow never waited on the first workflow's lock")


def _race(first, second, reached, release):
    """Release gates and close worker connections even if lock observation fails."""
    pid_queue, pids, outcomes, workers = queue.Queue(), {}, {}, []

    def run(name, operation):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
                cursor.execute("SELECT pg_backend_pid()")
                pids[name] = cursor.fetchone()[0]
                pid_queue.put(pids[name])
            outcomes[name] = (operation(), None)
        except Exception as exc:
            outcomes[name] = (None, exc)
        finally:
            connections.close_all()

    def start(name, operation):
        worker = threading.Thread(target=run, args=(name, operation), daemon=True)
        workers.append((name, worker))
        worker.start()
        return pid_queue.get(timeout=5)

    try:
        first_pid = start("first", first)
        assert reached.wait(5), "First workflow never reached its pause point"
        second_pid = start("second", second)
        _wait_until_blocked(second_pid, first_pid)
    finally:
        release.set()
        deadline = time.monotonic() + 20
        for _, worker in workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        # Last-resort cleanup keeps a failed assertion from leaking a DB session
        # or a thread into the next transactional test.
        for name, worker in workers:
            if worker.is_alive() and name in pids:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_terminate_backend(%s)", [pids[name]])
                worker.join(timeout=5)
        assert all(not worker.is_alive() for _, worker in workers), "Worker did not exit"

    for _, error in outcomes.values():
        if error is not None:
            raise error
    return outcomes["first"][0], outcomes["second"][0]


@pytest.mark.parametrize("is_active", [True, False], ids=["active", "inactive"])
@pytest.mark.parametrize("first", ["submit", "setup"], ids=["submit-first", "setup-first"])
def test_setup_and_submit_serialize_without_deadlock(settings, monkeypatch, is_active, first):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and separate connections")
    # Use the real self-host quota path, which does not acquire a makerspace lock.
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    space = make_space("queue-submission-race")
    actor = make_member("queue-submission-race", space)
    # Transactional flushes can remove the migration-seeded global type.
    printer, _ = MachineType.objects.get_or_create(
        makerspace=None, slug="3d_printer", defaults={
            "name": "3D printer", "is_builtin": True,
            "managing_action": "manage_printing", "capability_config": PRINTER_CONFIG,
        },
    )
    target = ServiceQueue.objects.create(
        makerspace=space, machine_type=printer, name="Public Requests",
        is_active=is_active, capacity=7, allocation_policy="first_idle",
        description="Keep operator settings",
    )
    before = AuditLog.objects.count()
    # Only delivery is stubbed: target locking, guards, validation, writes and
    # audit all run through the production workflow.
    monkeypatch.setattr("apps.machines.service_workflow_helpers.notify_service_status", lambda *args: None)
    reached, release = threading.Event(), threading.Event()

    def pause():
        reached.set()
        assert release.wait(10), "Timed out waiting to release the workflow"

    if first == "submit":
        require_module = service_workflow_actions._require_module

        def paused_module(*args, **kwargs):
            # Submit has taken its target locks but has not rechecked the module.
            pause()
            return require_module(*args, **kwargs)

        monkeypatch.setattr(service_workflow_actions, "_require_module", paused_module)
    else:
        active_queue = service_public_queue._active_queue

        def paused_queue(*args, **kwargs):
            # Setup holds the makerspace lock but has not locked any queue yet.
            pause()
            return active_queue(*args, **kwargs)

        monkeypatch.setattr(service_public_queue, "_active_queue", paused_queue)

    def setup():
        return service_public_queue.enable_public_queue(actor, space)

    def submission():
        try:
            return submit(
                target, actor, actor=actor, requester_name="Maker",
                contact_email=actor.email, contact_phone="1", title="Bracket",
                capability_payload=PRINTER_PAYLOAD,
            )
        except ServiceMachineUnavailable as exc:
            return exc

    operations = (submission, setup) if first == "submit" else (setup, submission)
    results = _race(*operations, reached, release)
    submitted, state = results if first == "submit" else results[::-1]
    if first == "submit" and not is_active:
        # Submission serialized before activation must refuse, without writes;
        # after setup commits the very same real submission succeeds.
        assert isinstance(submitted, ServiceMachineUnavailable)
        assert str(submitted) == "Service queue is inactive."
        assert not MachineServiceRequest.objects.filter(makerspace=space).exists()
        assert not AuditLog.objects.filter(makerspace=space, action="machine_service.submitted").exists()
        submitted = submission()
    assert isinstance(submitted, MachineServiceRequest)
    assert state == {"enabled": True, "queue_id": target.pk, "name": target.name}
    # Repeated setup is a no-op after both active-queue lookup and activation.
    assert setup() == state
    assert setup() == state
    assert ServiceQueue.objects.filter(makerspace=space).count() == 1
    target.refresh_from_db()
    assert target.is_active
    assert (target.name, target.capacity, target.allocation_policy, target.description) == (
        "Public Requests", 7, "first_idle", "Keep operator settings",
    )
    persisted = MachineServiceRequest.objects.get(makerspace=space)
    assert persisted.pk == submitted.pk
    assert persisted.queue_id == target.pk and persisted.bucket_id is None
    assert persisted.assigned_machine_id is None
    assert persisted.requester_id == actor.pk
    assert persisted.status == MachineServiceRequest.Status.PENDING
    assert persisted.title == "Bracket" and persisted.capability_payload == PRINTER_PAYLOAD
    events = AuditLog.objects.filter(makerspace=space)
    assert events.filter(action="machine_service.public_queue_created").count() == 0
    activations = events.filter(action="machine_service.public_queue_activated")
    assert activations.count() == int(not is_active)
    if not is_active:
        assert activations.get().target_id == str(target.pk)
    submitted_event = events.get(action="machine_service.submitted")
    assert submitted_event.target_id == str(persisted.pk)
    assert submitted_event.actor_id == actor.pk
    assert AuditLog.objects.count() == before + 1 + int(not is_active)
