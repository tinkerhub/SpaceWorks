"""Public queue writes must coexist with a real printer start and its FK checks."""
import threading
from decimal import Decimal

import pytest
from django.db import connection

from apps.audit.models import AuditLog
from apps.machines import role_scope, service_public_queue, service_workflow_actions
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceQueue
from apps.machines.printer_capabilities import PRINTER_CONFIG
from apps.machines.service_consumable_pools import create_pool
from apps.machines.service_workflow import accept, start, submit
from tests.machines.test_public_queue_submission_concurrency import PRINTER_PAYLOAD, _race
from tests.return_helpers import make_member, make_space, make_user
from tests.test_machine_printer_type_b3 import printer

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("competitor", ["setup", "submit"])
def test_public_queue_activity_does_not_deadlock_printer_start(settings, monkeypatch, competitor):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and deferred FK checks")
    # Exercise the real self-host quota path without unrelated managed limits.
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    # Transactional flushes can remove the migration-seeded built-in type.
    machine_type, _ = MachineType.objects.get_or_create(
        makerspace=None, slug="3d_printer", defaults={
            "name": "3D printer", "is_builtin": True,
            "managing_action": "manage_printing", "capability_config": PRINTER_CONFIG,
        },
    )
    space = make_space(f"queue-start-{competitor}")
    actor = make_member(f"queue-start-{competitor}-staff", space)
    requester = make_user(f"queue-start-{competitor}-requester")
    target = printer(space)
    public_queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=machine_type, name="Public Requests",
        is_active=True, capacity=7, allocation_policy="first_idle",
        description="Keep operator settings",
    )
    # Only outbound delivery is stubbed; notifications still register on commit.
    monkeypatch.setattr(
        "apps.machines.service_workflow_helpers.notify_service_status", lambda *args: None,
    )
    pool = create_pool(
        space, actor, machine=target, material="PLA", color="Blue", initial_grams="100",
    )

    def submission(title):
        return submit(
            public_queue, requester, actor=requester, requester_name="Maker",
            contact_email=requester.email, contact_phone="1", title=title,
            capability_payload=PRINTER_PAYLOAD,
        )

    job = submission("First bracket")
    accept(job, actor, estimated_minutes=30)
    events = AuditLog.objects.filter(makerspace=space)
    before = events.count()
    reached, release = threading.Event(), threading.Event()
    audit_transition = service_workflow_actions._audit_transition

    def paused_audit(actor, service_request, event, extra=None):
        if service_request.pk == job.pk and event == "assigned":
            # start() holds the request, queue, printer and pool locks here.
            # Keep real audit inserts and deferred FK checks inside its atomic
            # transaction: setup/submit may hold Makerspace FOR UPDATE while
            # waiting for this queue, blocking start's KEY SHARE at commit.
            reached.set()
            assert release.wait(15), "Timed out waiting to release printer start"
        return audit_transition(actor, service_request, event, extra=extra)

    monkeypatch.setattr(service_workflow_actions, "_audit_transition", paused_audit)

    def start_job():
        return start(
            job, actor, role_scope.EXEMPT, machine_id=target.pk,
            consumable_pool_id=pool.pk, planned_grams="20",
        )

    def setup():
        return service_public_queue.enable_public_queue(actor, space)

    competing_operation = setup if competitor == "setup" else lambda: submission("Second bracket")
    # _race waits for pg_blocking_pids(second) to contain the start connection
    # before releasing it, propagates either transaction's error, and always
    # joins workers/closes their DB connections with bounded timeout cleanup.
    started, result = _race(start_job, competing_operation, reached, release)

    job.refresh_from_db()
    target.refresh_from_db()
    pool.refresh_from_db()
    assert started.pk == job.pk
    assert job.status == MachineServiceRequest.Status.IN_PROGRESS
    assert job.assigned_machine_id == target.pk
    assert target.status == Machine.Status.RUNNING
    assert job.run_machine_model == "MK4"
    assert job.run_consumable_pool_id == pool.pk
    assert (job.run_consumable_material, job.run_consumable_color) == ("PLA", "Blue")
    assert job.reserved_grams == Decimal("20.00")
    assert pool.remaining_grams == Decimal("80.00")

    state = {"enabled": True, "queue_id": public_queue.pk, "name": "Public Requests"}
    requests = MachineServiceRequest.objects.filter(makerspace=space)
    pending = requests.filter(status=MachineServiceRequest.Status.PENDING)
    if competitor == "setup":
        assert result == state
        assert requests.count() == 1
        assert not pending.exists()
    else:
        assert requests.count() == 2
        second = pending.get()
        assert result.pk == second.pk and second.pk != job.pk
        assert second.queue_id == public_queue.pk and second.bucket_id is None
        assert second.assigned_machine_id is None
        assert second.requester_id == requester.pk
        assert second.title == "Second bracket"
        assert second.capability_payload == PRINTER_PAYLOAD
        assert events.get(action="machine_service.submitted", target_id=str(second.pk)).actor_id == requester.pk

    # Setup remains idempotent, including after the second pending submission.
    assert setup() == state
    assert setup() == state
    assert ServiceQueue.objects.filter(makerspace=space).count() == 1
    public_queue.refresh_from_db()
    assert public_queue.is_active
    assert (public_queue.name, public_queue.capacity, public_queue.allocation_policy, public_queue.description) == (
        "Public Requests", 7, "first_idle", "Keep operator settings",
    )
    assert not events.filter(action__in=[
        "machine_service.public_queue_created", "machine_service.public_queue_activated",
    ]).exists()
    assert events.filter(action="machine_service.submitted").count() == 1 + int(competitor == "submit")
    for action in ("accepted", "assigned", "started"):
        event = events.get(action=f"machine_service.{action}")
        assert event.target_id == str(job.pk) and event.actor_id == actor.pk
    assert events.filter(action="machine_consumable_pool.reserve").count() == 1
    assert events.count() == before + 3 + int(competitor == "submit")
