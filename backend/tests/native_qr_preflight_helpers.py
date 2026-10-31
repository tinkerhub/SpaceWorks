"""Persisted-state and native dispatch checks shared by QR refusal regressions."""

from functools import wraps
from unittest.mock import Mock

import pytest
from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.boxes import admin as boxes_admin, qr_admission
from apps.boxes.admin_qr_lifecycle import QrRebindAdminForm
from apps.boxes.models import BoxScan, QrCode, QrScanEvent
from apps.inventory.models import InventoryAsset, InventoryProduct


def qr_persisted_state():
    # No tenant filter or field projection: catch changes to other tenants and to
    # fields beyond the obvious QR target, including counters and timestamps.
    return {
        model._meta.label_lower: list(model.objects.order_by("pk").values())
        for model in (QrCode, InventoryProduct, InventoryAsset, QrScanEvent,
                      BoxScan, AuditLog, LogEntry)
    }


def record_qr_history(qr, actor):
    """Give refusal snapshots existing evidence and both kinds of audit history."""
    QrScanEvent.objects.create(
        makerspace=qr.makerspace, qr_code=qr, actor=actor,
        context=QrScanEvent.Context.INVENTORY_CHECK,
    )
    audit.record(actor, "qr.scanned", makerspace=qr.makerspace, target=qr)
    LogEntry.objects.create(
        user_id=actor.pk, content_type=ContentType.objects.get_for_model(qr),
        object_id=str(qr.pk), object_repr=str(qr), action_flag=CHANGE,
        change_message="Existing inventory check",
    )


def assert_rebind_error(response, qr, payload, message):
    assert response.status_code == 200
    assert response.template_name == "admin/boxes/rebind_qr.html"
    form = response.context_data["form"]
    assert isinstance(form, QrRebindAdminForm)
    assert form.is_bound
    assert set(form.errors) == {"__all__"}
    assert list(form.non_field_errors()) == [message]
    for field, value in payload.items():
        assert form.data[field] == str(value)
    assert list(response.context_data["queryset"].values_list("pk", flat=True)) == [qr.pk]
    assert message.encode() in response.content
    assert b"ErrorDetail(" not in response.content


@pytest.fixture
def no_qr_dispatch(monkeypatch):
    """Fail closed if refusal reaches locking, tenant admission, action or service."""
    forms = []
    original_init = QrRebindAdminForm.__init__

    @wraps(original_init)
    def capture_form(form, *args, **kwargs):
        original_init(form, *args, **kwargs)
        forms.append(form)

    monkeypatch.setattr(QrRebindAdminForm, "__init__", capture_form)
    model_admin = admin.site._registry[QrCode]
    blockers = {
        name: Mock(side_effect=AssertionError(f"Preflight refusal entered {name}"))
        for name in ("locked rows", "action", "service", "tenant boundary")
    }
    monkeypatch.setattr(model_admin, "_qr_rows", blockers["locked rows"])
    original_action = type(model_admin).rebind_selected

    @wraps(original_action)
    def forbidden_action(*args, **kwargs):
        return blockers["action"](*args, **kwargs)

    monkeypatch.setattr(type(model_admin), "rebind_selected", forbidden_action)
    monkeypatch.setattr(boxes_admin, "rebind_qr_target", blockers["service"])
    monkeypatch.setattr(qr_admission, "boundary_tenant_write", blockers["tenant boundary"])
    yield forms
    for blocker in blockers.values():
        blocker.assert_not_called()
