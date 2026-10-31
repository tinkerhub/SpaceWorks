"""Reprints share creation limits, locking and immutable attachment provenance."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.machines import role_scope, service_workflow_followups as followups
from apps.machines.models import MachineServiceRequest, ServiceRequestFile
from apps.machines.service_workflow import accept, complete, start
from apps.payments.models import Payment
from tests.return_helpers import make_space, make_user
from tests.test_machine_service_api import request_row


pytestmark = pytest.mark.django_db


def finish(row, actor):
    row.refresh_from_db()
    if row.status == MachineServiceRequest.Status.PENDING:
        accept(row, actor, estimated_minutes=10)
    start(row, actor, role_scope.EXEMPT, machine_id=row.bucket.machine_id)
    complete(row, actor, actual_minutes=3, consumptions=[])
    row.refresh_from_db()
    return row


def terminal_reprint(space, actor):
    root = finish(request_row(space), actor)
    attachment = ServiceRequestFile.objects.create(
        service_request=root, makerspace=space, machine=root.bucket.machine,
        kind="attachment", object_key=f"service/{space.pk}/{uuid4().hex}.pdf",
        content_type="application/pdf", original_filename="retained-plan.pdf",
        size_bytes=23, owner_user_id=root.requester_id, attached_at=timezone.now(),
        file_policy_name="documents", file_policy_version=1,
    )
    original = finish(followups.create_reprint(root, actor), actor)
    return root, original, attachment


def set_caps(space, *, open_cap=100, daily_cap=100):
    space.resource_limit_overrides = {
        "machine_service_open": open_cap, "machine_service_submit": daily_cap,
    }
    space.save(update_fields=["resource_limit_overrides"])


def creation_snapshot(space):
    return (
        list(MachineServiceRequest.objects.filter(makerspace=space).order_by("pk").values()),
        list(AuditLog.objects.filter(makerspace=space, action="machine_service.reprint_created")
             .order_by("pk").values()),
    )


@pytest.mark.parametrize("cap", ["open", "daily"])
def test_managed_cap_rejects_reprint_without_child_or_audit(cap, settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    space, actor = make_space(f"reprint-{cap}-cap"), make_user(f"reprint-{cap}-actor")
    _root, original, _attachment = terminal_reprint(space, actor)
    if cap == "open":
        followups.create_reprint(original, actor)
        set_caps(space, open_cap=1)
    else:
        # Both terminal rows were submitted today; terminal status only frees the open cap.
        set_caps(space, daily_cap=2)
    before = creation_snapshot(space)

    with pytest.raises(ValidationError) as caught:
        followups.create_reprint(original, actor)

    assert caught.value.get_codes() == {"limit": "limit_reached"}
    assert creation_snapshot(space) == before


def test_locked_module_check_rejects_even_with_cached_enabled_space(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    space, actor = make_space("reprint-module-off"), make_user("reprint-module-actor")
    _root, original, _attachment = terminal_reprint(space, actor)
    # Leave original's related makerspace cached as enabled, as at the view boundary.
    assert "machine_service" in original.makerspace.enabled_modules
    space.enabled_modules = [key for key in space.enabled_modules if key != "machine_service"]
    space.save(update_fields=["enabled_modules"])
    before = creation_snapshot(space)

    with pytest.raises(ValidationError) as caught:
        followups.create_reprint(original, actor)

    assert "module" in caught.value.detail
    assert creation_snapshot(space) == before


def test_self_host_ignores_caps_retains_root_files_and_resets_payment(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    space, actor = make_space("reprint-self-host"), make_user("reprint-self-host-actor")
    root, original, attachment = terminal_reprint(space, actor)
    original.payment_amount, original.payment_status, original.paid_at = Decimal("12.00"), "paid", timezone.now()
    original.save(update_fields=["payment_amount", "payment_status", "paid_at"])
    file_before = ServiceRequestFile.objects.filter(pk=attachment.pk).values().get()
    set_caps(space, open_cap=0, daily_cap=0)

    child = followups.create_reprint(original, actor)

    assert child.status == MachineServiceRequest.Status.ACCEPTED
    assert child.reprint_of_id == root.pk != original.pk
    assert (child.requester_id, child.member_id, child.bucket_id, child.queue_id) == (
        original.requester_id, original.member_id, original.bucket_id, original.queue_id,
    )
    for field in ("title", "description", "source_link", "capability_payload", "requester_name",
                  "contact_email", "contact_phone", "estimated_minutes", "planned_grams"):
        assert getattr(child, field) == getattr(original, field)
    assert (child.payment_amount, child.payment_status, child.paid_at) == (None, "none", None)
    assert not Payment.objects.filter(subject_type="machine_service_request", subject_id=child.pk).exists()
    assert ServiceRequestFile.objects.filter(pk=attachment.pk).values().get() == file_before
    assert list(child.reprint_of.files.values_list("pk", flat=True)) == [attachment.pk]
    assert not child.files.exists()
    audit = AuditLog.objects.get(action="machine_service.reprint_created", target_id=str(child.pk))
    assert audit.meta["reprint_of_id"] == root.pk


def test_reprint_lock_order_is_fence_then_makerspace_then_original(monkeypatch):
    space, actor = make_space("reprint-lock-order"), make_user("reprint-lock-actor")
    _root, original, _attachment = terminal_reprint(space, actor)
    calls = []
    fence, gate, lock = (followups._assert_request_write_allowed,
                         followups.require_module_locked, followups._locked_request)

    def fenced(row):
        result = fence(row)
        calls.append("fence")
        return result

    def gated(space_id, module, **kwargs):
        assert calls == ["fence"]
        assert (space_id, module, kwargs) == (space.pk, "machine_service", {"no_key": True})
        result = gate(space_id, module, **kwargs)
        calls.append("makerspace")
        return result

    def locked(row):
        assert calls == ["fence", "makerspace"]
        calls.append("original")
        return lock(row)

    monkeypatch.setattr(followups, "_assert_request_write_allowed", fenced)
    monkeypatch.setattr(followups, "require_module_locked", gated)
    monkeypatch.setattr(followups, "_locked_request", locked)
    followups.create_reprint(original, actor)
    assert calls == ["fence", "makerspace", "original"]


@pytest.mark.django_db(transaction=True)
def test_distinct_originals_contend_for_one_managed_slot(monkeypatch, settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    space, actor = make_space("reprint-last-slot"), make_user("reprint-last-slot-actor")
    originals = [terminal_reprint(space, actor)[1] for _ in range(2)]
    set_caps(space, open_cap=1)
    before_ids = set(MachineServiceRequest.objects.filter(makerspace=space).values_list("pk", flat=True))
    before_audits = AuditLog.objects.filter(makerspace=space, action="machine_service.reprint_created").count()
    barrier = Barrier(2, timeout=10)
    real_gate = followups.require_module_locked

    def contended_gate(*args, **kwargs):
        # Rendezvous BEFORE acquiring the shared makerspace lock, never while holding it.
        barrier.wait()
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(followups, "require_module_locked", contended_gate)

    def create(original_id):
        close_old_connections()
        try:
            row = MachineServiceRequest.objects.get(pk=original_id)
            try:
                child = followups.create_reprint(row, actor)
                return "created", child.pk
            except ValidationError as exc:
                assert exc.get_codes() == {"limit": "limit_reached"}
                return "limited", None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create, row.pk) for row in originals]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sorted(status for status, _pk in outcomes) == ["created", "limited"]
    children = MachineServiceRequest.objects.filter(makerspace=space).exclude(pk__in=before_ids)
    assert children.count() == 1
    assert children.get().pk == next(pk for status, pk in outcomes if status == "created")
    assert children.get().status == MachineServiceRequest.Status.ACCEPTED
    assert AuditLog.objects.filter(makerspace=space, action="machine_service.reprint_created").count() == before_audits + 1
