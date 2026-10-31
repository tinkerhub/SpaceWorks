"""BOX-S01 fresh-row authority through the central service and HTTP serializer."""
import pytest
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.boxes.models import QrCode
from apps.boxes.services import revoke_qr_code
from apps.hardware_requests.models import PublicToolLoan
from tests.box_checkout_guard_helpers import (
    assert_png_promoted, checkout, checkout_lab, root_kit, snapshot, uploaded_photo,
)

pytestmark = pytest.mark.django_db


def test_revoke_api_serializes_the_fresh_revoked_instance(monkeypatch, settings):
    lab = checkout_lab(monkeypatch, settings)
    _, stale = root_kit(lab)
    response = lab.client.post(f"/api/v1/admin/qr/{stale.pk}/revoke")
    assert response.status_code == 200, response.data
    assert response.data["id"] == stale.pk
    assert response.data["status"] == QrCode.Status.REVOKED
    assert response.data["revoked_at"] is not None
    fresh = QrCode.objects.get(pk=stale.pk)
    assert fresh.status == QrCode.Status.REVOKED and fresh.revoked_at is not None
    # The service re-fetches a locked row; the caller's old Python object is stale.
    assert stale.status == QrCode.Status.ACTIVE and stale.revoked_at is None
    event = AuditLog.objects.get(makerspace=lab.space, action="qr.revoked")
    assert (event.actor_id, event.target_id) == (lab.actor.pk, str(stale.pk))


def test_stale_active_instance_cannot_revoke_twice_or_append_audit(monkeypatch, settings):
    lab = checkout_lab(monkeypatch, settings)
    _, stale = root_kit(lab)
    fresh = revoke_qr_code(lab.actor, stale)
    assert fresh is not stale
    assert fresh.pk == stale.pk and fresh.status == QrCode.Status.REVOKED
    assert stale.status == QrCode.Status.ACTIVE
    assert AuditLog.objects.filter(makerspace=lab.space, action="qr.revoked").count() == 1
    before = snapshot()
    with pytest.raises(ValidationError, match="already revoked") as rejected:
        revoke_qr_code(lab.actor, stale)
    assert rejected.value.status_code == 400
    assert snapshot() == before
    response = lab.client.post(f"/api/v1/admin/qr/{stale.pk}/revoke")
    assert response.status_code == 400, response.data
    assert "already revoked" in str(response.data)
    assert snapshot() == before


@pytest.mark.parametrize("entrypoint", ["service", "api"])
@pytest.mark.parametrize("target", ["box", "secondary-asset"])
def test_real_active_public_loan_blocks_revoke_without_mutation(
    monkeypatch, settings, entrypoint, target,
):
    lab = checkout_lab(monkeypatch, settings, "put", individual=target == "secondary-asset")
    if target == "box":
        _, qr = root_kit(lab)
        qrs = [qr]
    else:
        qrs = lab.qrs[:2]
        qr = qrs[1]
    evidence = uploaded_photo(lab, "public")
    response = checkout(lab, "public", qrs, evidence)
    assert response.status_code == 201, response.data
    loan = PublicToolLoan.objects.get()
    assert loan.status == "checked_out"
    assert qr.pk in loan.qr_ids
    if target == "secondary-asset":
        assert loan.qr_code_id != qr.pk  # Guard must consult the full qr_ids ledger.
    assert_png_promoted(lab, evidence, charged=True)
    before = snapshot()
    if entrypoint == "service":
        with pytest.raises(ValidationError, match="outstanding loan") as rejected:
            revoke_qr_code(lab.actor, qr)
        assert rejected.value.status_code == 400
    else:
        response = lab.client.post(f"/api/v1/admin/qr/{qr.pk}/revoke")
        assert response.status_code == 400, response.data
        assert "outstanding loan" in str(response.data)
    assert snapshot() == before
    qr.refresh_from_db()
    assert qr.status == QrCode.Status.ACTIVE and qr.revoked_at is None
    assert not AuditLog.objects.filter(makerspace=lab.space, action="qr.revoked").exists()
