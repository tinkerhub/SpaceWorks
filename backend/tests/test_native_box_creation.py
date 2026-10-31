"""BOX-S03/05: use the actual /control/ add, edit and delete routes."""
import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.boxes.models import Box, QrCode
from tests.qr_target_safety_helpers import (
    fail_after_insert, native_client, native_form, qr_lab,
    request_qr, snapshot, superadmin, target,
)
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db


def create_native(case, client, **changes):
    url, data = native_form(client, "boxes_box", makerspace=case.home.pk,
                            label="Native container", is_active="on", **changes)
    response = client.post(url, data)
    assert response.status_code == 302, getattr(response, "context", None)
    return Box.objects.get(label=data["label"], makerspace=case.home)


def test_native_box_add_creates_matching_usable_qr(qr_lab):
    actor = superadmin()
    box = create_native(qr_lab, native_client(actor))
    qr = QrCode.objects.get(makerspace=qr_lab.home, target_type="box", target_id=box.pk)
    assert qr.payload == box.code and qr.status == "active" and qr.created_by_id == actor.pk
    row = AuditLog.objects.get(action="qr.box_created", target_id=str(box.pk))
    assert (row.target_type, row.makerspace_id, row.actor_id) == ("boxes.box", qr_lab.home.pk, actor.pk)
    response = request_qr(qr_lab, "resolve", qr)
    assert response.status_code == 200
    assert response.data["target"] == {"type": "box", "id": box.pk, "code": box.code, "label": box.label}
    assert request_qr(qr_lab, "scan", qr).status_code == 201


def test_native_unscanned_box_delete_retains_active_qr_but_all_target_routes_refuse(qr_lab):
    client = native_client(superadmin())
    box = create_native(qr_lab, client)
    qr = QrCode.objects.get(target_type="box", target_id=box.pk, makerspace=qr_lab.home)
    box_id = box.pk
    response = client.post(reverse("admin:boxes_box_delete", args=[box_id]), {"post": "yes"})
    assert response.status_code == 302
    assert not Box.objects.filter(pk=box_id).exists()
    qr.refresh_from_db()
    assert qr.status == "active" and qr.target_id == box_id
    before = snapshot()
    for operation in ("resolve", "scan", "print", "batch"):
        response = request_qr(qr_lab, operation, qr)
        assert response.status_code == 404, (operation, response.data)
        assert snapshot() == before


def test_native_add_audit_insert_then_refusal_rolls_back_box_qr_and_admin_log(qr_lab, monkeypatch):
    client = native_client(superadmin())
    url, data = native_form(client, "boxes_box", makerspace=qr_lab.home.pk, label="Rollback box")
    inserted = fail_after_insert(monkeypatch, "qr.box_created")
    before = snapshot()
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        client.post(url, data)
    assert len(inserted) == 1
    assert snapshot() == before


def test_native_box_add_preserves_valid_parent(qr_lab):
    parent = target(qr_lab.home, "box")
    box = create_native(qr_lab, native_client(superadmin()), parent=parent.pk)
    assert box.parent_id == parent.pk
    assert QrCode.objects.get(target_type="box", target_id=box.pk).payload == box.code


@pytest.mark.parametrize("invalid", ["foreign-parent", "duplicate"])
def test_native_box_add_model_errors_are_form_errors_without_partial_rows(qr_lab, invalid):
    existing = target(qr_lab.home, "box")
    client = native_client(superadmin())
    changes = {"label": "Invalid native child"}
    if invalid == "foreign-parent":
        changes["parent"] = target(qr_lab.other, "box").pk
    else:
        changes["label"] = existing.label
    url, data = native_form(client, "boxes_box", makerspace=qr_lab.home.pk, **changes)
    before = snapshot()
    response = client.post(url, data)
    assert response.status_code == 200
    errors = response.context["adminform"].form.errors
    assert errors and ("parent" in errors if invalid == "foreign-parent" else "already exists" in str(errors))
    assert snapshot() == before


@pytest.mark.parametrize("qr_state", ["absent", "active", "revoked"])
def test_existing_native_box_edit_never_recreates_or_reactivates_qr(qr_lab, qr_state):
    client = native_client(superadmin())
    box = target(qr_lab.home, "box")
    if qr_state != "absent":
        QrCode.objects.create(makerspace=qr_lab.home, payload=box.code,
                              target_type="box", target_id=box.pk, status=qr_state)
    before = list(QrCode.objects.order_by("pk").values())
    url, data = native_form(client, "boxes_box", box, label="Renamed native box")
    assert client.post(url, data).status_code == 302
    box.refresh_from_db()
    assert box.label == "Renamed native box"
    assert list(QrCode.objects.order_by("pk").values()) == before
    # BoxAdmin edit audit is a separately pending source follow-up, not asserted here.


@pytest.mark.parametrize("denial", ["suspended", "hidden", "source-gate", "non-superuser"])
def test_native_add_guard_refusals_have_no_box_qr_or_audit_writes(qr_lab, denial):
    actor = superadmin()
    client = native_client(actor)
    url, data = native_form(client, "boxes_box", makerspace=qr_lab.home.pk, label="Denied native box")
    if denial == "suspended":
        actor.access_status = "suspended"
        actor.save(update_fields=["access_status"])
    elif denial == "hidden":
        qr_lab.home.superadmin_access_enabled = False
        qr_lab.home.save(update_fields=["superadmin_access_enabled"])
    elif denial == "source-gate":
        close_gate(qr_lab.home, actor)
    else:
        actor.is_superuser = False
        actor.save(update_fields=["is_superuser"])
    before = snapshot()
    response = client.post(url, data)
    assert response.status_code == {"suspended": 403, "hidden": 200, "source-gate": 423,
                                    "non-superuser": 403}[denial]
    if denial == "hidden":
        assert response.context["adminform"].form.errors
    assert snapshot() == before


def test_native_raw_qr_add_is_still_disabled(qr_lab):
    client = native_client(superadmin())
    before = snapshot()
    assert client.post(reverse("admin:boxes_qrcode_add"), {
        "makerspace": qr_lab.home.pk, "target_type": "box", "target_id": 99999,
    }).status_code == 403
    assert snapshot() == before
