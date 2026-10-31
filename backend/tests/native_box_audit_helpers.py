"""Native audit observations; bulk canonical state deliberately excludes LogEntry.

Django delete_selected logs deletion attempts BEFORE delete_queryset. Those ordinary
diagnostics are outside the approved helper transaction and are asserted separately.
No parent-creation/deletion race is exercised by these sequential tests.
"""
from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.inventory.models import Category
from apps.operations.models import QrPrintBatch
from tests.qr_target_safety_helpers import (
    native_client, native_form, qr_for, snapshot, superadmin, target,
)


def canonical_and_domain_state():
    """Whole rows of affected domain models + canonical audit, NOT admin attempts.

    Includes both tenants, related products/assets, boxes/children, categories,
    QR/scans, print batches/items and every AuditLog column. Counts alone would
    miss SET_NULL, timestamp or metadata mutations on surviving rows.
    """
    state = snapshot(Category, BoxScan, QrPrintBatch)
    del state[LogEntry._meta.label_lower]
    return state


def native_attempt_state():
    return list(LogEntry.objects.order_by("pk").values())


def assert_native_deletion_attempts(before, case):
    after = native_attempt_state()
    assert after[:len(before)] == before
    attempts = after[len(before):]
    assert len(attempts) == len(case.objects) == 2
    content_type = ContentType.objects.get_for_model(case.model).pk
    assert {(row["object_id"], row["object_repr"]) for row in attempts} == {
        (str(obj.pk), str(obj)) for obj in case.objects
    }
    for row in attempts:
        assert row["user_id"] == case.actor.pk
        assert row["content_type_id"] == content_type
        assert row["action_flag"] == DELETION
        assert row["change_message"] == ""


def bulk_post(case):
    data = {"action": "delete_selected", "select_across": "0", "post": "yes",
            ACTION_CHECKBOX_NAME: [str(obj.pk) for obj in case.objects]}
    return case.client.post(reverse(f"admin:{case.name}_changelist"), data)


def create_native_box(lab, client):
    url, data = native_form(client, "boxes_box", makerspace=lab.home.pk,
                            label="Native private container", is_active="on")
    response = client.post(url, data)
    assert response.status_code == 302, getattr(response, "context", None)
    return Box.objects.get(makerspace=lab.home, label=data["label"])


def assert_box_update(row, actor, box, changed):
    assert (row.action, row.actor_id, row.makerspace_id, row.target_type, row.target_id) == (
        "control.object_updated", actor.pk, box.makerspace_id, "boxes.box", str(box.pk),
    )
    assert row.meta == {"model": "boxes.box", "changed_fields": sorted(changed), "detail": {}}
    for value in (box.label, box.location, box.description):
        if value:
            assert value not in str(row.meta)


def refuse_after_delete_insert(monkeypatch, ordinal):
    """Only fault injection: let the real audit persist before the caller refuses."""
    real_record, inserted = audit.record, []

    def record(actor, action, **kwargs):
        row = real_record(actor, action, **kwargs)
        if action == "control.object_deleted":
            assert AuditLog.objects.filter(pk=row.pk).exists()
            inserted.append(row.pk)
            if len(inserted) == ordinal:
                raise RuntimeError("Bulk refusal after real audit INSERT")
        return row

    monkeypatch.setattr(audit, "record", record)
    return inserted


def protected_history(lab, actor):
    box = target(lab.home, "box")
    qr = qr_for(lab.home, box, "box", payload=box.code, created_by=actor)
    scan = BoxScan.objects.create(makerspace=lab.home, box=box, actor=actor, context="issue")
    QrScanEvent.objects.create(makerspace=lab.home, qr_code=qr, actor=actor, context="issue")
    return box, scan


@pytest.fixture(params=["box", "category"])
def bulk_case(qr_lab, request):
    actor = superadmin()
    is_box = request.param == "box"
    model = Box if is_box else Category
    objects, links = [], []
    for index, tenant in enumerate((qr_lab.home, qr_lab.other)):
        if is_box:
            obj = target(tenant, "box")
            qr_for(tenant, obj, "box", payload=obj.code,
                   status="active" if index == 0 else "revoked", created_by=actor)
            child = Box.objects.create(makerspace=tenant, parent=obj, label="Surviving child")
            links.append(("boxes.box", child.pk, "parent_id"))
        else:
            obj = Category.objects.create(makerspace=tenant, name="Private bulk category",
                                          slug="private-bulk-category")
        product = target(tenant, "product")
        field = "box" if is_box else "category"
        setattr(product, field, obj)
        product.save(update_fields=[field])
        links.append((product._meta.label_lower, product.pk, f"{field}_id"))
        objects.append(obj)
    return SimpleNamespace(
        lab=qr_lab, actor=actor, client=native_client(actor), model=model,
        name="boxes_box" if is_box else "inventory_category", objects=objects, links=links,
        model_admin=admin.site._registry[model],
    )
