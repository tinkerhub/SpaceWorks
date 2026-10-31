"""HW003: native control actions and real QR rebind FK compatibility."""
import threading

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection
from django.test import RequestFactory

from apps.audit.models import AuditLog
from apps.boxes import rebind
from apps.boxes.admin import QrCodeAdmin
from apps.boxes.models import QrCode, QrScanEvent
from apps.hardware_requests import self_checkout_workflow
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from tests.checkout_lock_fixture_helpers import (
    client, finalized, loan_trace, product_qr, public_checkout, quota,
    return_public, setup_lab, stock,
)
from tests.checkout_lock_race_helpers import pause_audit, race
from tests.inventory_lending_evidence_helpers import photo
from tests.return_helpers import make_product

pytestmark = pytest.mark.django_db(transaction=True)


def native_revoke(root_id, qr_id):
    """Invoke the actual ModelAdmin action with real request/session/messages."""
    request = RequestFactory().post("/control/boxes/qrcode/", {
        "action": "revoke_selected", "_selected_action": [str(qr_id)],
    })
    SessionMiddleware(lambda request: None).process_request(request)
    request._messages = FallbackStorage(request)
    request.user = get_user_model().objects.get(pk=root_id)
    model_admin = QrCodeAdmin(QrCode, admin.site)
    assert model_admin.has_change_permission(request)
    selected = model_admin.get_queryset(request).filter(pk=qr_id)
    assert selected.count() == 1
    model_admin.revoke_selected(request, selected)
    return [str(message) for message in request._messages]


@pytest.mark.parametrize("transport", ["post", "put"])
@pytest.mark.parametrize("winner", ["checkout", "revoke"])
def test_native_revoke_vs_public_checkout_waits_real_qr_and_rechecks(
    monkeypatch, settings, transport, winner,
):
    lab = setup_lab(monkeypatch, settings, transport)
    qr = product_qr(lab)
    root = get_user_model().objects.create_superuser(
        username="native-qr-root", email="native-root@example.test", password="unused-race-secret",
        access_status="active", role="superadmin",
    )
    image = photo(lab, lab.store, "issue")
    operations = {
        "checkout": lambda: public_checkout(lab, qr, image),
        "revoke": lambda: native_revoke(root.pk, qr.pk),
    }
    reached, release = pause_audit(
        monkeypatch, "public_tool.checked_out" if winner == "checkout" else "qr.revoked",
    )
    loser = "revoke" if winner == "checkout" else "checkout"

    def committed_active():
        assert QrCode.objects.get(pk=qr.pk).status == "active"
        assert not PublicToolLoan.objects.filter(makerspace=lab.space).exists()
        stock(lab, 1, 0, 0)
        quota(lab, 0)

    first, second, pids, query = race(
        operations[winner], operations[loser], reached, release,
        table="boxes_qrcode", clause="FOR UPDATE", before_second=committed_active,
    )

    assert len(set(pids.values())) == 2 and 'FROM "boxes_qrcode"' in query
    qr.refresh_from_db()
    if winner == "checkout":
        assert first.status_code == 201, first.data
        assert any("outstanding loan" in message for message in second), second
        assert "Revoked 0 QR code(s); skipped 1." in second
        assert qr.status == "active" and qr.revoked_at is None
        assert not AuditLog.objects.filter(makerspace=lab.space, action="qr.revoked").exists()
        loan = PublicToolLoan.objects.get(makerspace=lab.space)
        loan_trace(lab, loan, qr, image, direct=False)
        stock(lab, 0, 0, 1)
        quota(lab, 1)
        # Refusing native revoke must leave the real QR usable for legitimate return.
        return_public(lab, qr)
        stock(lab, 1, 0, 0)
        quota(lab, 2)
    else:
        assert "Revoked 1 QR code(s); skipped 0." in first
        assert second.status_code == 400, second.data
        assert "QR code is not active" in str(second.data)
        assert qr.status == "revoked" and qr.revoked_at is not None
        entry = AuditLog.objects.get(makerspace=lab.space, action="qr.revoked")
        assert entry.actor_id == root.pk and entry.target_id == str(qr.pk)
        assert not HardwareRequest.objects.filter(makerspace=lab.space).exists()
        assert not PublicToolLoan.objects.filter(makerspace=lab.space).exists()
        assert not QrScanEvent.objects.filter(makerspace=lab.space).exists()
        assert not AuditLog.objects.filter(
            makerspace=lab.space, action__in=["public_tool.checked_out", "evidence.attached"],
        ).exists()
        finalized(lab, image, charged=False)
        stock(lab, 1, 0, 0)
        quota(lab, 0)


@pytest.mark.parametrize("transport", ["post", "put"])
def test_real_rebind_scan_and_audit_fks_commit_while_checkout_holds_maker_nk(
    monkeypatch, settings, transport,
):
    lab = setup_lab(monkeypatch, settings, transport)
    qr = product_qr(lab)
    destination = make_product(
        lab.space, name="Rebound target", total_quantity=1, available_quantity=1,
        public_self_checkout_enabled=True,
    )
    image = photo(lab, lab.store, "issue")
    reached, release, maker_locked = threading.Event(), threading.Event(), threading.Event()
    target = rebind.target_for_rebind
    guard = self_checkout_workflow.require_feature_locked

    def observe_target(*args, **kwargs):
        result = target(*args, **kwargs)
        if kwargs.get("locked", True):
            # The actual service has locked and authorized QR + destination; its real
            # scan/audit FK writes and deferred constraint checks still lie ahead.
            assert connection.in_atomic_block
            reached.set()
            assert release.wait(12), "Rebind target checkpoint was not released"
        return result

    def observe_maker(*args, **kwargs):
        result = guard(*args, **kwargs)
        assert kwargs["no_key"] is True and connection.in_atomic_block
        maker_locked.set()
        return result

    monkeypatch.setattr(rebind, "target_for_rebind", observe_target)
    monkeypatch.setattr(self_checkout_workflow, "require_feature_locked", observe_maker)

    def rebind_target():
        # The API owns transaction + real IsActiveStaff/RBAC/module/target guards.
        return client(lab).post(f"/api/v1/admin/qr/{qr.pk}/rebind-target", {
            "target_type": "product", "target_id": destination.pk,
        }, format="json")

    rebound, checked_out, _, query = race(
        rebind_target, lambda: public_checkout(lab, qr, image), reached, release,
        table="boxes_qrcode", clause="FOR UPDATE",
    )

    assert maker_locked.is_set() and 'FROM "boxes_qrcode"' in query
    assert rebound.status_code == 200, rebound.data
    assert checked_out.status_code == 201, checked_out.data
    qr.refresh_from_db()
    assert qr.target_id == destination.pk and qr.target_type == "product" and qr.status == "active"
    reassigned = QrScanEvent.objects.get(qr_code=qr, context="reassignment")
    assert reassigned.actor_id == lab.actor.pk and reassigned.makerspace_id == lab.space.pk
    entry = AuditLog.objects.get(makerspace=lab.space, action="qr.rebound")
    assert entry.actor_id == lab.actor.pk
    assert entry.meta["old_target_id"] == lab.product.pk and entry.meta["new_target_id"] == destination.pk
    loan = PublicToolLoan.objects.get(makerspace=lab.space)
    loan_trace(lab, loan, qr, image, direct=False)
    assert loan.target_id == destination.pk and loan.target_label == destination.name
    stock(lab, 1, 0, 0)  # The stale target was never issued.
    destination.refresh_from_db()
    assert (destination.available_quantity, destination.issued_quantity) == (0, 1)
    quota(lab, 1)
    return_public(lab, qr)
    destination.refresh_from_db()
    assert (destination.available_quantity, destination.issued_quantity) == (1, 0)
    quota(lab, 2)
