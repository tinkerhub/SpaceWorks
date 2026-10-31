"""Canonical audit through registered native QR forms/actions, including rollback."""
import pytest
from django.contrib.admin.models import DELETION, LogEntry
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.boxes.models import QrCode, QrScanEvent
from tests.qr_source_safety.http_helpers import bulk_request, closure_lab, prepared
from tests.qr_source_safety.state_helpers import (
    assert_canonical, audit_ids, audits_since, state,
)
from tests.qr_target_safety_helpers import fail_after_insert, native_form, qr_for, target

pytestmark = pytest.mark.django_db(transaction=True)


def deletion(lab, mode, codes):
    if mode == "single":
        return lambda: lab.native.post(
            reverse("admin:boxes_qrcode_delete", args=[codes[0].pk]), {"post": "yes"})
    return bulk_request(lab.native, codes)


def codes(lab, count):
    return [qr_for(lab.home, target(lab.home, "product"), "product", created_by=lab.root)
            for _ in range(count)]


def assert_attempts(before, actor, selected):
    rows = list(LogEntry.objects.exclude(pk__in=before))
    assert len(rows) == len(selected)
    assert {(row.user_id, row.object_id, row.action_flag) for row in rows} == {
        (actor.pk, str(qr.pk), DELETION) for qr in selected}


def test_native_created_by_edit_audits_only_field_names(closure_lab):
    lab = closure_lab
    case = prepared(lab, "native-edit")
    before = audit_ids()
    assert case.call().status_code == 302
    case.qr.refresh_from_db()
    assert case.qr.created_by_id == lab.actor.pk
    rows = audits_since(before)
    assert len(rows) == 1
    assert_canonical(rows[0], lab.root, case.qr)
    assert str(lab.actor.pk) not in str(rows[0].meta)
    assert lab.actor.username not in str(rows[0].meta)


def test_native_noop_has_no_canonical_audit(closure_lab):
    lab = closure_lab
    qr = codes(lab, 1)[0]
    url, data = native_form(lab.native, "boxes_qrcode", qr)
    before = state(attempts=False)
    assert lab.native.post(url, data).status_code == 302
    after = state(attempts=False)
    # Django's ordinary save touches auto_now even when form.changed_data is empty.
    for snapshot in (before, after):
        for row in snapshot["boxes.qrcode"]:
            row.pop("updated_at")
    assert after == before


@pytest.mark.parametrize("mode", ["single", "bulk"])
def test_native_delete_has_exact_canonical_events(closure_lab, mode):
    lab = closure_lab
    selected = codes(lab, 1 if mode == "single" else 2)
    before, attempts = audit_ids(), set(LogEntry.objects.values_list("pk", flat=True))
    assert deletion(lab, mode, selected)().status_code == 302
    assert not QrCode.objects.filter(pk__in=[qr.pk for qr in selected]).exists()
    rows = audits_since(before)
    assert len(rows) == len(selected)
    for qr in selected:
        row = next(row for row in rows if row.target_id == str(qr.pk))
        assert_canonical(row, lab.root, qr, deleted=True)
    assert_attempts(attempts, lab.root, selected)


@pytest.mark.parametrize("mode", ["single", "bulk"])
def test_actual_native_history_protects_qr_delete_without_audit(closure_lab, mode):
    lab = closure_lab
    selected = codes(lab, 1 if mode == "single" else 2)
    QrScanEvent.objects.create(makerspace=lab.home, qr_code=selected[0], actor=lab.actor,
                               context=QrScanEvent.Context.SCANNER_LOOKUP)
    before = state()
    response = deletion(lab, mode, selected)()
    assert response.status_code == 200
    assert response.context["protected"]
    assert state() == before


@pytest.mark.parametrize("kind", ["native-edit", "native-single", "native-bulk"])
def test_real_native_audit_insert_then_refusal_rolls_back_domain_and_canonical(closure_lab, monkeypatch, kind):
    lab = closure_lab
    case = prepared(lab, kind)
    selected = [case.qr]
    if kind == "native-bulk":
        selected += codes(lab, 1)
        case.call = bulk_request(lab.native, selected)
    action = "control.object_updated" if kind == "native-edit" else "control.object_deleted"
    inserted = fail_after_insert(monkeypatch, action)
    before = state(attempts=False)
    attempts = set(LogEntry.objects.values_list("pk", flat=True))
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        case.call()
    assert len(inserted) == 1
    assert not AuditLog.objects.filter(pk__in=inserted).exists()
    assert state(attempts=False) == before
    # Accepted Django limitation: bulk attempt LogEntry precedes delete_queryset's
    # atomic helper. These are diagnostic attempts, separate from canonical audit.
    if kind == "native-bulk":
        assert_attempts(attempts, lab.root, selected)
    else:
        assert not LogEntry.objects.exclude(pk__in=attempts).exists()


@pytest.mark.parametrize("kind,event", [("native-revoke", "qr.revoked"),
                                        ("native-rebind", "qr.rebound")])
def test_native_custom_actions_keep_exact_service_event_without_control_duplicate(closure_lab, kind, event):
    lab = closure_lab
    case = prepared(lab, kind)
    before = audit_ids()
    assert case.call().status_code == 302
    rows = audits_since(before)
    assert len(rows) == 1
    row = rows[0]
    assert (row.action, row.actor_id, row.makerspace_id, row.target_type, row.target_id) == (
        event, lab.root.pk, lab.home.pk, "boxes.qrcode", str(case.qr.pk))
    assert not any(row.action.startswith("control.") for row in rows)
    assert row.meta == ({} if kind == "native-revoke" else {
        "old_makerspace_id": lab.home.pk, "old_target_type": "product",
        "old_target_id": case.obj.pk, "new_makerspace_id": lab.home.pk,
        "new_target_type": "product", "new_target_id": case.destination.pk, "new_name": "",
    })


def test_native_qr_add_stays_denied(closure_lab):
    lab = closure_lab
    before = state()
    response = lab.native.post(reverse("admin:boxes_qrcode_add"), {
        "makerspace": lab.home.pk, "target_type": "product", "target_id": 123,
        "created_by": lab.root.pk, "_save": "Save",
    })
    assert response.status_code == 403
    assert state() == before
