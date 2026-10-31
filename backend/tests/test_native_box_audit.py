"""Box edit + shared canonical bulk audit delta; no parent-race coverage.

Bulk rollback covers canonical AuditLog and whole domain rows. Native Django
LogEntry deletion-attempt diagnostics precede the helper and remain separately.
"""
from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.boxes.admin import BoxAdmin
from apps.boxes.models import Box, QrCode
from apps.inventory.admin import CategoryAdmin
from config.admin_audit import AdminAuditMixin
from config.admin_source_gate import AdminSourceGateMixin
from tests.native_box_audit_helpers import (
    assert_box_update, assert_native_deletion_attempts, bulk_case, bulk_post,
    canonical_and_domain_state, create_native_box, native_attempt_state,
    protected_history, refuse_after_delete_insert,
)
from tests.qr_target_safety_helpers import (
    fail_after_insert, native_client, native_form, qr_for, qr_lab, snapshot,
    superadmin, target,
)
from tests.tenant_migration.source_gate_helpers import close_gate

# Autocommit matters: a test-wide atomic would hide the native bulk LogEntry boundary.
pytestmark = pytest.mark.django_db(transaction=True)


def test_native_box_add_has_one_service_event_and_no_duplicate_control_create(qr_lab):
    actor = superadmin()
    before = set(AuditLog.objects.values_list("pk", flat=True))
    box = create_native_box(qr_lab, native_client(actor))
    rows = list(AuditLog.objects.exclude(pk__in=before))
    assert len(rows) == 1
    row = rows[0]
    assert (row.action, row.actor_id, row.makerspace_id, row.target_type, row.target_id) == (
        "qr.box_created", actor.pk, qr_lab.home.pk, "boxes.box", str(box.pk),
    )
    qr = QrCode.objects.get(makerspace=qr_lab.home, target_type="box", target_id=box.pk)
    assert (qr.payload, qr.status, qr.created_by_id) == (box.code, "active", actor.pk)


@pytest.mark.parametrize("qr_state", ["absent", "active", "revoked"])
def test_native_box_edit_audits_only_field_names_and_preserves_qr_rows(qr_lab, qr_state):
    actor = superadmin()
    client = native_client(actor)
    box = target(qr_lab.home, "box")
    if qr_state != "absent":
        qr_for(qr_lab.home, box, "box", payload=box.code, status=qr_state,
               revoked_at=timezone.now() if qr_state == "revoked" else None, created_by=actor)
    qr_before = list(QrCode.objects.order_by("pk").values())
    before = list(AuditLog.objects.order_by("pk").values())
    changes = {"label": "Private renamed label", "location": "Private shelf location",
               "description": "Private borrower description"}
    url, data = native_form(client, "boxes_box", box, **changes)
    assert client.post(url, data).status_code == 302
    box.refresh_from_db()
    for name, value in changes.items():
        assert getattr(box, name) == value
    after = list(AuditLog.objects.order_by("pk").values())
    assert after[:-1] == before and len(after) == len(before) + 1
    assert_box_update(AuditLog.objects.get(pk=after[-1]["id"]), actor, box, changes)
    assert list(QrCode.objects.order_by("pk").values()) == qr_before


def test_native_box_noop_has_no_extra_canonical_audit(qr_lab):
    client = native_client(superadmin())
    box = create_native_box(qr_lab, client)
    url, data = native_form(client, "boxes_box", box)
    before = canonical_and_domain_state()
    assert client.post(url, data).status_code == 302
    after = canonical_and_domain_state()
    for state in (before, after):
        for row in state["boxes.box"]:
            row.pop("updated_at")
    assert after == before


def test_native_changeform_real_audit_insert_refusal_rolls_back_box_audit_and_logentry(qr_lab, monkeypatch):
    client = native_client(superadmin())
    box = create_native_box(qr_lab, client)
    url, data = native_form(client, "boxes_box", box, label="Rollback private label",
                            location="Rollback private location")
    before = snapshot()
    inserted = fail_after_insert(monkeypatch, "control.object_updated")
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        client.post(url, data)
    assert len(inserted) == 1
    assert not AuditLog.objects.filter(pk__in=inserted).exists()
    # Unlike bulk delete_selected, the actual changeform owns this whole transaction.
    assert snapshot() == before


def test_registered_bulk_consumers_resolve_the_shared_helper_without_provider_wrappers(bulk_case):
    case = bulk_case
    expected = BoxAdmin if case.model is Box else CategoryAdmin
    assert type(case.model_admin) is expected
    mro = type(case.model_admin).__mro__
    assert AdminAuditMixin in mro and AdminSourceGateMixin in mro
    owner = next(cls for cls in mro if "delete_queryset" in cls.__dict__)
    if case.model is Box:
        from apps.boxes.admin_lifecycle import BoxLifecycleMixin

        assert owner is BoxLifecycleMixin
        assert case.model_admin.delete_queryset.__func__ is BoxLifecycleMixin.delete_queryset
        assert mro.index(BoxLifecycleMixin) < mro.index(AdminAuditMixin)
        assert super(BoxLifecycleMixin, case.model_admin).delete_queryset.__func__ is AdminAuditMixin.delete_queryset
    else:
        assert owner is AdminAuditMixin
        assert case.model_admin.delete_queryset.__func__ is AdminAuditMixin.delete_queryset


def test_real_native_bulk_success_has_exactly_two_canonical_events_and_collector_updates(bulk_case):
    case = bulk_case
    before = canonical_and_domain_state()
    attempts = native_attempt_state()
    assert bulk_post(case).status_code == 302
    after = canonical_and_domain_state()
    prior_ids = {row["id"] for row in before["audit.auditlog"]}
    rows = list(AuditLog.objects.exclude(pk__in=prior_ids))
    assert len(rows) == 2
    assert {(row.target_id, row.makerspace_id) for row in rows} == {
        (str(obj.pk), obj.makerspace_id) for obj in case.objects
    }
    for row in rows:
        assert row.actor_id == case.actor.pk and row.action == "control.object_deleted"
        assert row.target_type == case.model._meta.label_lower
        assert row.meta == {"model": case.model._meta.label_lower}
    # Compare every surviving column, including related rows changed by SET_NULL.
    key = case.model._meta.label_lower
    deleted = {obj.pk for obj in case.objects}
    before[key] = [row for row in before[key] if row["id"] not in deleted]
    for key, pk, field in case.links:
        next(row for row in before[key] if row["id"] == pk)[field] = None
    assert [row for row in after["audit.auditlog"] if row["id"] in prior_ids] == before["audit.auditlog"]
    del before["audit.auditlog"], after["audit.auditlog"]
    assert after == before
    assert_native_deletion_attempts(attempts, case)


@pytest.mark.parametrize("ordinal", [1, 2])
def test_real_bulk_audit_insert_refusal_rolls_back_canonical_and_domain_state_only(bulk_case, monkeypatch, ordinal):
    case = bulk_case
    assert connection.get_autocommit() and not connection.in_atomic_block
    before, attempts = canonical_and_domain_state(), native_attempt_state()
    inserted = refuse_after_delete_insert(monkeypatch, ordinal)
    with pytest.raises(RuntimeError, match="Bulk refusal after real audit INSERT"):
        bulk_post(case)
    assert len(inserted) == ordinal
    assert not AuditLog.objects.filter(pk__in=inserted).exists()
    assert canonical_and_domain_state() == before
    # Native admin attempt records intentionally survive; they are NOT canonical audits.
    assert_native_deletion_attempts(attempts, case)


@pytest.mark.parametrize("denial", ["source-gate", "hidden", "suspended", "non-superuser"])
def test_native_box_edit_preserves_guards_without_audit_or_domain_writes(qr_lab, denial):
    actor = superadmin()
    client = native_client(actor)
    box = target(qr_lab.home, "box")
    url, data = native_form(client, "boxes_box", box, label="Denied private rename")
    if denial == "source-gate":
        close_gate(qr_lab.home, actor)
    elif denial == "hidden":
        qr_lab.home.superadmin_access_enabled = False
        qr_lab.home.save(update_fields=["superadmin_access_enabled"])
    else:
        setattr(actor, "access_status" if denial == "suspended" else "is_superuser",
                "suspended" if denial == "suspended" else False)
        actor.save(update_fields=["access_status" if denial == "suspended" else "is_superuser"])
    before = snapshot()
    response = client.post(url, data)
    assert response.status_code == {"source-gate": 423, "hidden": 302,
                                    "suspended": 403, "non-superuser": 403}[denial]
    assert snapshot() == before


@pytest.mark.parametrize("denial", ["source-gate", "hidden", "suspended", "non-superuser"])
def test_native_bulk_preserves_guards_without_canonical_or_attempt_writes(bulk_case, denial):
    case = bulk_case
    if denial == "source-gate":
        close_gate(case.lab.home, case.actor)
    elif denial == "hidden":
        # Hide BOTH selected tenants so no visible subset can legitimately be deleted.
        for tenant in (case.lab.home, case.lab.other):
            tenant.superadmin_access_enabled = False
            tenant.save(update_fields=["superadmin_access_enabled"])
    else:
        field = "access_status" if denial == "suspended" else "is_superuser"
        setattr(case.actor, field, "suspended" if denial == "suspended" else False)
        case.actor.save(update_fields=[field])
    before, attempts = canonical_and_domain_state(), native_attempt_state()
    response = bulk_post(case)
    assert response.status_code == {"source-gate": 423, "hidden": 302,
                                    "suspended": 403, "non-superuser": 403}[denial]
    assert canonical_and_domain_state() == before
    assert native_attempt_state() == attempts


@pytest.mark.parametrize("operation", ["single", "bulk"])
def test_native_protected_box_history_refuses_at_preflight_without_losing_qr_or_scans(qr_lab, operation):
    actor = superadmin()
    client = native_client(actor)
    box, _scan = protected_history(qr_lab, actor)
    before, attempts = canonical_and_domain_state(), native_attempt_state()
    if operation == "single":
        response = client.post(reverse("admin:boxes_box_delete", args=[box.pk]), {"post": "yes"})
    else:
        case = SimpleNamespace(client=client, name="boxes_box", objects=[box])
        response = bulk_post(case)
    assert response.status_code == 200
    assert response.context["protected"]
    assert canonical_and_domain_state() == before
    assert native_attempt_state() == attempts


def test_registered_box_bulk_helper_rolls_back_real_audit_when_real_collector_protects_history(qr_lab):
    actor = superadmin()
    box, scan = protected_history(qr_lab, actor)
    other = target(qr_lab.home, "box")
    request = RequestFactory().post("/control/boxes/box/", {"action": "delete_selected"})
    request.user = actor
    before, attempts = canonical_and_domain_state(), native_attempt_state()
    # Component proof: native preflight above never reaches this callback. Observe SQL,
    # without replacing the audit function, queryset.delete, guards or Collector.
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(ProtectedError) as exc:
            admin.site._registry[Box].delete_queryset(request, Box.objects.filter(pk__in=[box.pk, other.pk]))
    assert scan in exc.value.protected_objects
    inserts = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith("INSERT INTO")
               and f'"{AuditLog._meta.db_table}"' in query["sql"]]
    assert len(inserts) == 2
    assert canonical_and_domain_state() == before
    assert native_attempt_state() == attempts
