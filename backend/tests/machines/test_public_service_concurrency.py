"""Observe actual PostgreSQL wait edges for typed intake vs staff and first POSTs."""
import threading

import pytest
from django.db import connection

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.machines import public_service_intake, public_service_legacy, role_scope, service_workflow_actions
from apps.machines.models import Machine, MachineConsumablePool, MachineServiceRequest, ServiceBucket, ServiceQueue, ServiceRequestFile
from apps.machines.public_service_intake import stage_typed_upload, submit_typed_request
from apps.machines.service_workflow import accept, start, submit
from tests.machines.public_service_helpers import object_io, service_lab
from tests.machines.test_public_queue_submission_concurrency import _race

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def managed_limits(settings, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL locks and separate DB connections")
    settings.PLATFORM_DOMAIN_SUFFIX = "spaces.example.test"
    # Nonempty numeric caps exercise the real quota and storage row locks.
    settings.MANAGED_RESOURCE_LIMITS = {
        "machine_service_open": 2, "machine_service_submit": 2, "print": 2, "storage": 10000,
    }
    monkeypatch.setattr("apps.machines.service_workflow_helpers.notify_service_status", lambda *args: None)


@pytest.mark.parametrize("first", ["start", "submit"])
def test_typed_printer_submit_with_managed_quota_and_storage_coexists_with_staff_start(service_lab, object_io, monkeypatch, first):
    space, actor, _, _, printer = service_lab
    machine = Machine.objects.get(makerspace=space, machine_type=printer)
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=printer, name="Public printer queue")
    job = submit_typed_request(space, {"machine_type_id": printer.pk, "title": "First run"}, actor)
    accept(job, actor, estimated_minutes=20)
    pool = MachineConsumablePool.objects.create(makerspace=space, machine_type=printer, material="PLA", color="Blue",
                                                initial_grams=100, remaining_grams=100)
    staged = stage_typed_upload(space, {"machine_type_id": printer.pk, "kind": "stl", "filename": "part.stl",
                                       "content_type": "model/stl", "queue_id": queue.pk}, actor)
    file = ServiceRequestFile.objects.get(pk=staged["file_id"])
    data = b"solid bracket\nendsolid bracket"
    object_io[0][file.object_key] = (data, "model/stl")
    reached, release = threading.Event(), threading.Event()

    def pause():
        reached.set()
        assert release.wait(15), "Timed out releasing first workflow"

    if first == "start":
        real_audit = service_workflow_actions._audit_transition

        def paused_audit(actor, row, event, extra=None):
            if row.pk == job.pk and event == "assigned":
                # Staff holds queue, machine and pool; keep the real audit FK writes.
                pause()
            return real_audit(actor, row, event, extra=extra)

        monkeypatch.setattr(service_workflow_actions, "_audit_transition", paused_audit)
    else:
        real_lock = public_service_intake.lock_attachments

        def paused_files(*args):
            files = real_lock(*args)
            # Intake holds makerspace NO KEY UPDATE, queue and staged files.
            pause()
            return files

        monkeypatch.setattr(public_service_intake, "lock_attachments", paused_files)

    def intake():
        return submit_typed_request(space, {"machine_type_id": printer.pk, "title": "Second run",
                                            "queue_id": queue.pk, "file_ids": [file.pk]}, actor)

    def staff_start():
        return start(job, actor, role_scope.EXEMPT, machine_id=machine.pk, consumable_pool_id=pool.pk, planned_grams="20")

    operations = (staff_start, intake) if first == "start" else (intake, staff_start)
    results = _race(*operations, reached, release)
    started, submitted = results if first == "start" else results[::-1]
    job.refresh_from_db()
    pool.refresh_from_db()
    space.refresh_from_db()
    file.refresh_from_db()
    assert started.pk == job.pk and job.status == "in_progress" and job.assigned_machine_id == machine.pk
    assert pool.remaining_grams == 80 and job.reserved_grams == 20
    pending = MachineServiceRequest.objects.get(pk=submitted.pk)
    assert pending.status == "pending" and pending.assigned_machine_id is None and pending.queue_id == queue.pk
    assert file.service_request_id == pending.pk and file.attached_at is not None and file.size_bytes == len(data)
    assert space.storage_bytes_used == len(data)
    assert MachineServiceRequest.objects.filter(makerspace=space).count() == 2
    assert ServiceQueue.objects.filter(makerspace=space).count() == 1
    assert AuditLog.objects.filter(makerspace=space, action="machine_service.submitted").count() == 2
    assert AuditLog.objects.filter(makerspace=space, action="machine_service.started", target_id=str(job.pk)).count() == 1
    # These are actual finite managed limits, not mocked counters/unlimited paths.
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):
        submit_typed_request(space, {"machine_type_id": printer.pk, "title": "Over quota"}, actor)
    assert MachineServiceRequest.objects.filter(makerspace=space).count() == 2


def test_concurrent_first_typed_posts_create_one_queue_and_two_jobs(service_lab, monkeypatch):
    space, actor, _, generic, _ = service_lab
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    reached, release = threading.Event(), threading.Event()
    real_record = audit.record

    def pause_first_creation(actor, action, **kwargs):
        if action == "machine_service.public_queue_created":
            reached.set()
            assert release.wait(15), "Timed out releasing queue creation"
        return real_record(actor, action, **kwargs)

    monkeypatch.setattr(audit, "record", pause_first_creation)

    def intake(title):
        return submit_typed_request(space, {"machine_type_id": generic.pk, "title": title}, actor)

    one, two = _race(lambda: intake("First"), lambda: intake("Second"), reached, release)
    assert one.pk != two.pk and one.queue_id == two.queue_id
    assert one.status == two.status == "pending" and one.assigned_machine_id is two.assigned_machine_id is None
    assert ServiceQueue.objects.filter(makerspace=space, machine_type=generic).count() == 1
    assert set(MachineServiceRequest.objects.filter(makerspace=space).values_list("title", flat=True)) == {"First", "Second"}
    events = AuditLog.objects.filter(makerspace=space)
    assert events.filter(action="machine_service.public_queue_created").count() == 1
    assert events.filter(action="machine_service.submitted").count() == 2


@pytest.mark.parametrize("first", ["legacy", "staff"])
@pytest.mark.parametrize("staff_target", ["machine", "bucket"])
def test_legacy_and_direct_staff_submissions_share_lock_order(service_lab, monkeypatch, first, staff_target):
    space, actor, _, generic, _ = service_lab
    machine = Machine.objects.get(makerspace=space, machine_type=generic)
    # Legacy machine-id callers may still request private machines.
    machine.is_public = False
    machine.save(update_fields=["is_public"])
    bucket = ServiceBucket.objects.create(machine=machine, name="Service Requests")
    reached, release = threading.Event(), threading.Event()

    def pause():
        reached.set()
        assert release.wait(15), "Timed out releasing first submission"

    if first == "legacy":
        real_module = public_service_legacy.require_module

        def paused_public_module(*args, **kwargs):
            # The public wrapper holds makerspace, before taking the machine.
            pause()
            return real_module(*args, **kwargs)

        monkeypatch.setattr(public_service_legacy, "require_module", paused_public_module)
    else:
        real_module = service_workflow_actions._require_module

        def paused_staff_module(*args, **kwargs):
            # Shared submit has locked its target, before the locked module check.
            # The old machine-first path deadlocks here with the public wrapper.
            pause()
            return real_module(*args, **kwargs)

        monkeypatch.setattr(service_workflow_actions, "_require_module", paused_staff_module)

    def legacy():
        return public_service_legacy.submit_legacy_machine(space, machine.pk, {"title": "Legacy"}, actor)

    def staff():
        return submit(bucket if staff_target == "bucket" else machine, actor, actor=actor,
                      requester_name="Ada Maker", contact_email=actor.email, contact_phone=actor.phone, title="Staff")

    operations = (legacy, staff) if first == "legacy" else (staff, legacy)
    one, two = _race(*operations, reached, release)
    assert one.pk != two.pk
    jobs = MachineServiceRequest.objects.filter(makerspace=space)
    assert jobs.count() == 2
    assert set(jobs.values_list("title", flat=True)) == {"Legacy", "Staff"}
    assert all(job.status == "pending" and job.bucket_id == bucket.pk
               and job.assigned_machine_id == machine.pk and job.queue_id is None for job in jobs)
    events = AuditLog.objects.filter(makerspace=space, action="machine_service.submitted")
    assert set(events.values_list("target_id", flat=True)) == {str(one.pk), str(two.pk)}
    assert events.count() == 2 and all(event.actor_id == actor.pk for event in events)
    assert ServiceBucket.objects.filter(machine=machine).count() == 1
    # Real finite managed quotas still reject a third job after both commits.
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):
        staff()
    assert jobs.all().count() == 2 and events.all().count() == 2
