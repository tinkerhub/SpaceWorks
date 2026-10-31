"""Resolve keeps its DTO/VIEW authority and appends one scan plus canonical audit."""
from uuid import uuid4

import pytest
from django.db import DatabaseError, transaction
from django.urls import reverse

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.boxes.models import QrCode, QrScanEvent
from apps.accounts.models import User
from apps.makerspaces.models import Makerspace
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.qr_source_safety.http_helpers import closure_lab
from tests.qr_source_safety.state_helpers import audit_ids, audits_since, state
from tests.qr_target_safety_helpers import fail_after_insert, jwt_client, qr_for, staff, target

pytestmark = pytest.mark.django_db(transaction=True)
QR_FIELDS = {"id", "makerspace", "payload", "target_type", "target_id", "status",
             "created_at", "updated_at", "revoked_at"}


def reader(lab):
    actor = staff(lab.home, "member")
    role = MakerspaceRole.objects.create(
        makerspace=lab.home, name="Inventory reader", slug=f"reader-{uuid4().hex[:8]}",
        granted_actions=[rbac.Action.VIEW_INVENTORY],
    )
    MakerspaceMembership.objects.filter(user=actor, makerspace=lab.home).update(
        role="custom", assigned_role=role,
    )
    assert rbac.can(actor, rbac.Action.VIEW_INVENTORY, lab.home.pk)
    assert not rbac.can(actor, rbac.Action.MANAGE_QR, lab.home.pk)
    return actor, jwt_client(actor)


def scan_audit(before, actor, qr, context):
    rows = audits_since(before)
    assert len(rows) == 1
    scan = QrScanEvent.objects.get(qr_code=qr)
    row = rows[0]
    assert (scan.makerspace_id, scan.actor_id, scan.qr_code_id, scan.context, scan.request_id) == (
        qr.makerspace_id, actor.pk, qr.pk, context, None,
    )
    assert (row.action, row.actor_id, row.makerspace_id, row.target_type, row.target_id, row.meta) == (
        "qr.scanned", actor.pk, qr.makerspace_id, "boxes.qrcode", str(qr.pk),
        {"context": context, "scan_id": scan.pk},
    )
    return scan


@pytest.mark.parametrize("kind", ["box", "product", "asset"])
@pytest.mark.parametrize("view_only", [False, True])
def test_actual_resolve_one_immutable_lookup_and_exact_audit_with_unchanged_dto(closure_lab, kind, view_only):
    lab = closure_lab
    actor, client = reader(lab) if view_only else (lab.actor, lab.api)
    obj = target(lab.home, kind)
    qr = qr_for(lab.home, obj, kind)
    before = audit_ids()
    response = client.post(reverse("qr-resolve"), {"payload": qr.payload}, format="json")
    assert response.status_code == 200, response.data
    assert set(response.data) == {"qr", "target", "allowed_actions"}
    assert set(response.data["qr"]) == QR_FIELDS
    assert response.data["qr"]["id"] == qr.pk
    expected = ({"type": "box", "id": obj.pk, "label": obj.label, "code": obj.code}
                if kind == "box" else {"type": "product", "id": obj.pk, "name": obj.name}
                if kind == "product" else {"type": "asset", "id": obj.pk,
                    "asset_tag": obj.asset_tag, "product": obj.product.name, "status": obj.status})
    assert response.data["target"] == expected
    if view_only:
        assert response.data["allowed_actions"] == (["contents", "view"] if kind == "box" else ["view"])
    scan = scan_audit(before, actor, qr, QrScanEvent.Context.SCANNER_LOOKUP)
    immutable = state()
    with pytest.raises(RuntimeError, match="immutable"):
        scan.save()
    with pytest.raises(RuntimeError, match="immutable"):
        scan.delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        QrScanEvent.objects.filter(pk=scan.pk).update(context="issue")
    with pytest.raises(DatabaseError), transaction.atomic():
        QrScanEvent.objects.filter(pk=scan.pk).delete()
    assert state() == immutable


@pytest.mark.parametrize("kind", ["box", "product", "asset"])
def test_real_resolve_audit_insert_then_refusal_rolls_back_scan_and_audit(closure_lab, monkeypatch, kind):
    lab = closure_lab
    qr = qr_for(lab.home, target(lab.home, kind), kind)
    inserted = fail_after_insert(monkeypatch, "qr.scanned")
    before = state()
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        lab.api.post(reverse("qr-resolve"), {"payload": qr.payload}, format="json")
    assert len(inserted) == 1
    assert not AuditLog.objects.filter(pk__in=inserted).exists()
    assert state() == before


@pytest.mark.parametrize("kind", ["box", "product", "asset"])
def test_explicit_scan_still_has_exactly_one_event_and_one_audit(closure_lab, kind):
    lab = closure_lab
    qr = qr_for(lab.home, target(lab.home, kind), kind)
    before = audit_ids()
    response = lab.api.post(reverse("qr-scan"), {
        "payload": qr.payload, "context": "inventory_check",
    }, format="json")
    assert response.status_code == 201
    scan = scan_audit(before, lab.actor, qr, QrScanEvent.Context.INVENTORY_CHECK)
    assert response.data["scan_id"] == scan.pk
    assert set(response.data) == {"qr", "target", "scan_id"}


def test_view_inventory_reader_cannot_explicitly_scan_and_denial_writes_nothing(closure_lab):
    actor, client = reader(closure_lab)
    qr = qr_for(closure_lab.home, target(closure_lab.home, "product"), "product")
    before = state()
    response = client.post(reverse("qr-scan"), {
        "payload": qr.payload, "context": "inventory_check",
    }, format="json")
    assert response.status_code == 404
    assert state() == before


@pytest.mark.parametrize("denial,status", [
    ("unknown", 404), ("revoked", 404), ("missing-target", 404), ("foreign-target", 404),
    ("wrong-origin", 403), ("foreign-scope", 404), ("module-disabled", 400), ("suspended", 403),
])
def test_actual_resolve_denial_emits_neither_scan_nor_audit(closure_lab, denial, status):
    lab = closure_lab
    obj = target(lab.home, "product")
    qr = qr_for(lab.home, obj, "product")
    payload = qr.payload
    if denial == "unknown":
        payload = uuid4().hex
    elif denial == "revoked":
        QrCode.objects.filter(pk=qr.pk).update(status="revoked")
    elif denial == "missing-target":
        obj.delete()
    elif denial == "foreign-target":
        foreign = target(lab.other, "product")
        QrCode.objects.filter(pk=qr.pk).update(target_id=foreign.pk)
    elif denial == "wrong-origin":
        lab.api.defaults["HTTP_ORIGIN"] = f"https://{lab.other.frontend_domain}"
    elif denial == "foreign-scope":
        lab.api = jwt_client(staff(lab.other))
    elif denial == "module-disabled":
        Makerspace.objects.filter(pk=lab.home.pk).update(
            enabled_modules=[key for key in lab.home.enabled_modules if key != "scanner"])
    else:
        User.objects.filter(pk=lab.actor.pk).update(access_status="suspended")
    before = state()
    response = lab.api.post(reverse("qr-resolve"), {"payload": payload}, format="json")
    assert response.status_code == status, getattr(response, "data", response.content)
    assert state() == before
