"""BOX-S04: real HTTP mutations roll back even after an audit row was inserted."""
import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.boxes.models import QrCode
from tests.qr_target_safety_helpers import (
    fail_after_insert, jwt_client, membership, qr_for, qr_lab, request_qr,
    snapshot, staff, superadmin, target,
)
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db


def mutate(case, operation, obj=None):
    if operation == "box":
        return case.client.post(reverse("qr-boxes"), {
            "makerspace_id": case.home.pk, "label": "Atomic HTTP box",
        }, format="json")
    if operation == "scan":
        return request_qr(case, "scan", obj)
    return case.client.post(reverse("qr-tools"), {
        "makerspace_id": case.home.pk,
        "asset_id" if operation == "asset" else "product_id": obj.pk,
    }, format="json")


@pytest.mark.parametrize("operation", ["box", "product", "asset", "scan"])
def test_audit_insert_then_refusal_rolls_back_complete_api_mutation(qr_lab, monkeypatch, operation):
    obj = None if operation == "box" else target(qr_lab.home, "asset" if operation == "asset" else "product")
    if operation == "scan":
        obj = qr_for(qr_lab.home, obj, "product")
    action = "qr.box_created" if operation == "box" else "qr.scanned" if operation == "scan" else "qr.tool_created"
    inserted = fail_after_insert(monkeypatch, action)
    before = snapshot()

    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        mutate(qr_lab, operation, obj)

    assert len(inserted) == 1
    assert not AuditLog.objects.filter(pk=inserted[0]).exists()
    assert snapshot() == before


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_reused_tool_audit_refusal_does_not_mutate_existing_qr(qr_lab, monkeypatch, kind):
    obj = target(qr_lab.home, kind)
    qr = qr_for(qr_lab.home, obj, kind, created_by=qr_lab.actor)
    inserted = fail_after_insert(monkeypatch, "qr.tool_reused")
    before = snapshot()
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        mutate(qr_lab, kind, obj)
    assert len(inserted) == 1
    assert snapshot() == before
    qr.refresh_from_db()
    assert qr.status == "active"


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_successful_tool_reuse_keeps_payload_and_timestamps(qr_lab, kind):
    obj = target(qr_lab.home, kind)
    qr = qr_for(qr_lab.home, obj, kind, created_by=qr_lab.actor)
    before = QrCode.objects.filter(pk=qr.pk).values().get()
    response = mutate(qr_lab, kind, obj)
    assert response.status_code == 201, response.data
    assert response.data["id"] == qr.pk and response.data["payload"] == qr.payload
    assert QrCode.objects.filter(pk=qr.pk).values().get() == before
    row = AuditLog.objects.get(action="qr.tool_reused")
    assert (row.actor_id, row.makerspace_id, row.target_id) == (qr_lab.actor.pk, qr_lab.home.pk, str(obj.pk))


@pytest.mark.parametrize("operation", ["box", "product", "asset", "scan"])
def test_closed_source_gate_refuses_real_qr_writes(qr_lab, operation):
    obj = None if operation == "box" else target(qr_lab.home, "asset" if operation == "asset" else "product")
    if operation == "scan":
        obj = qr_for(qr_lab.home, obj, "product")
    close_gate(qr_lab.home, qr_lab.actor)
    before = snapshot()
    response = mutate(qr_lab, operation, obj)
    assert response.status_code == 423, response.data
    assert snapshot() == before


@pytest.mark.parametrize("operation,module", [("resolve", "scanner"), ("batch", "qr_print_batches")])
def test_optional_module_denial_has_no_mutation(qr_lab, operation, module):
    qr = qr_for(qr_lab.home, target(qr_lab.home, "product"), "product")
    qr_lab.home.enabled_modules = [key for key in qr_lab.home.enabled_modules if key != module]
    qr_lab.home.save(update_fields=["enabled_modules"])
    before = snapshot()
    response = request_qr(qr_lab, operation, qr)
    assert response.status_code == 400 and "module" in response.data
    assert snapshot() == before


@pytest.mark.parametrize("operation", ["box", "product", "asset"])
@pytest.mark.parametrize("denial", ["role", "origin", "suspended", "hidden"])
def test_creation_http_guard_refusals_do_not_mint_rows(qr_lab, operation, denial):
    obj = None if operation == "box" else target(qr_lab.home, operation)
    if denial == "role":
        qr_lab.client = jwt_client(staff(qr_lab.home, "member"))
    elif denial == "origin":
        membership(qr_lab.actor, qr_lab.other)
        qr_lab.client.defaults["HTTP_ORIGIN"] = f"https://{qr_lab.other.frontend_domain}"
    elif denial == "suspended":
        qr_lab.actor.access_status = "suspended"
        qr_lab.actor.save(update_fields=["access_status"])
    else:
        qr_lab.client = jwt_client(superadmin())
        qr_lab.home.superadmin_access_enabled = False
        qr_lab.home.save(update_fields=["superadmin_access_enabled"])
    before = snapshot()
    response = mutate(qr_lab, operation, obj)
    assert response.status_code == (403 if denial in {"origin", "suspended"} else 404)
    assert snapshot() == before
