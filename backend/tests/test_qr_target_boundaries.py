"""BOX-S03: generic targets are resolved by exact enum and QR tenant over HTTP."""
import pytest
from django.http import Http404
from django.urls import reverse

from apps.boxes.models import QrCode, QrScanEvent
from apps.makerspaces.models import MakerspaceRole
from apps.operations.services_qr_assets import add_qr_to_batch
from tests.qr_target_safety_helpers import (
    jwt_client, membership, qr_for, qr_lab, request_qr, snapshot, staff,
    superadmin, target,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", ["box", "product", "asset"])
@pytest.mark.parametrize("invalid", ["missing", "foreign"])
@pytest.mark.parametrize("operation", ["resolve", "scan", "print", "batch"])
def test_invalid_generic_target_is_404_without_writes(qr_lab, kind, invalid, operation):
    case = qr_lab
    obj = target(case.other if invalid == "foreign" else case.home, kind)
    target_id = obj.pk if invalid == "foreign" else obj.pk + 1000000
    qr = QrCode.objects.create(makerspace=case.home, target_type=kind, target_id=target_id)
    before = snapshot()

    response = request_qr(case, operation, qr)

    assert response.status_code == 404, response.data
    assert snapshot() == before


@pytest.mark.parametrize("operation", ["resolve", "scan", "print", "batch"])
def test_unknown_enum_cannot_fall_through_to_product(qr_lab, operation):
    obj = target(qr_lab.home, "product")
    qr = qr_for(qr_lab.home, obj, "not-a-target-kind")
    before = snapshot()
    assert request_qr(qr_lab, operation, qr).status_code == 404
    assert snapshot() == before


@pytest.mark.parametrize("kind", ["box", "product", "asset"])
@pytest.mark.parametrize("invalid", ["missing", "foreign", "unknown"])
def test_explicit_manual_label_cannot_bypass_service_target_validation(qr_lab, kind, invalid):
    obj = target(qr_lab.other if invalid == "foreign" else qr_lab.home, kind)
    qr = QrCode.objects.create(
        makerspace=qr_lab.home, target_type="unknown" if invalid == "unknown" else kind,
        target_id=obj.pk + 1000000 if invalid == "missing" else obj.pk,
    )
    before = snapshot()
    with pytest.raises(Http404):
        add_qr_to_batch(qr_lab.actor, qr_lab.batch, qr, label_text="Manual bypass attempt")
    assert snapshot() == before


@pytest.mark.parametrize("kind", ["box", "product", "asset"])
def test_valid_http_payload_identifies_the_canonical_target(qr_lab, kind):
    obj = target(qr_lab.home, kind)
    qr = qr_for(qr_lab.home, obj, kind)
    response = request_qr(qr_lab, "resolve", qr)
    assert response.status_code == 200, response.data
    assert response.data["target"]["id"] == obj.pk
    assert response.data["target"]["type"] == kind
    assert response.data["qr"]["makerspace"] == qr_lab.home.pk
    scan = QrScanEvent.objects.get(qr_code=qr)
    assert (scan.makerspace_id, scan.actor_id, scan.context) == (
        qr_lab.home.pk, qr_lab.actor.pk, "scanner_lookup",
    )


def test_valid_box_retains_batch_kind_restriction(qr_lab):
    qr = qr_for(qr_lab.home, target(qr_lab.home, "box"), "box")
    before = snapshot()
    response = request_qr(qr_lab, "batch", qr)
    assert response.status_code == 400
    assert "only accept inventory" in str(response.data)
    assert snapshot() == before


@pytest.mark.parametrize("operation", ["resolve", "scan", "print", "batch"])
@pytest.mark.parametrize("denial", ["foreign-member", "origin", "suspended", "hidden"])
def test_http_rbac_origin_and_account_guards_preserve_state(qr_lab, operation, denial):
    case = qr_lab
    qr = qr_for(case.home, target(case.home, "product"), "product")
    headers = {}
    if denial == "foreign-member":
        case.client = jwt_client(staff(case.other))
    elif denial == "origin":
        membership(case.actor, case.other)
        headers["HTTP_ORIGIN"] = f"https://{case.other.frontend_domain}"
    elif denial == "suspended":
        case.actor.access_status = "suspended"
        case.actor.save(update_fields=["access_status"])
    else:
        case.client = jwt_client(superadmin())
        case.home.superadmin_access_enabled = False
        case.home.save(update_fields=["superadmin_access_enabled"])
    before = snapshot()
    response = request_qr(case, operation, qr, **headers)
    assert response.status_code == (403 if denial in {"origin", "suspended"} else 404)
    assert snapshot() == before


def test_inventory_read_role_resolves_but_cannot_scan_or_print(qr_lab):
    actor = staff(qr_lab.home, "member")
    role = MakerspaceRole.objects.create(
        makerspace=qr_lab.home, name="Scanner reader", slug="scanner-reader",
        granted_actions=["view_inventory"],
    )
    member = actor.makerspace_memberships.get()
    member.role, member.assigned_role = "custom", role
    member.save(update_fields=["role", "assigned_role"])
    qr_lab.client = jwt_client(actor)
    qr = qr_for(qr_lab.home, target(qr_lab.home, "product"), "product")
    assert request_qr(qr_lab, "resolve", qr).status_code == 200
    before = snapshot()
    for operation in ("scan", "print", "batch"):
        assert request_qr(qr_lab, operation, qr).status_code == 404
        assert snapshot() == before


def test_revoked_qr_retains_history_and_print_behavior(qr_lab):
    qr = qr_for(qr_lab.home, target(qr_lab.home, "product"), "product")
    assert request_qr(qr_lab, "scan", qr).status_code == 201
    history = list(QrScanEvent.objects.filter(qr_code=qr).values())
    response = qr_lab.client.post(reverse("qr-revoke", args=[qr.pk]), {}, format="json")
    assert response.status_code == 200
    qr.refresh_from_db()
    assert qr.status == "revoked" and qr.revoked_at is not None
    before = snapshot()
    assert request_qr(qr_lab, "resolve", qr).status_code == 404
    assert request_qr(qr_lab, "scan", qr).status_code == 404
    assert request_qr(qr_lab, "print", qr).status_code == 200
    assert snapshot() == before
    assert list(QrScanEvent.objects.filter(qr_code=qr).values()) == history
