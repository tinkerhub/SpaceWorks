"""HW002: real competing handovers serialize before the old Box/QR cycle."""
import pytest

from apps.audit.models import AuditLog
from apps.boxes.models import BoxScan, QrScanEvent
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from tests.checkout_lock_fixture_helpers import (
    accept_and_assign, container, direct_checkout, finalized, loan_trace,
    public_checkout, quota, return_direct, return_public, return_reviewed,
    reviewed_issue, setup_lab, stock,
)
from tests.checkout_lock_race_helpers import pause_audit, race
from tests.inventory_lending_evidence_helpers import photo

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("transport", ["post", "put"])
@pytest.mark.parametrize("winner", ["direct", "public"])
def test_selected_quantity_box_vs_public_box_serializes_on_maker(
    monkeypatch, settings, transport, winner,
):
    lab = setup_lab(monkeypatch, settings, transport)
    box, qr = container(lab)
    images = {name: photo(lab, lab.store, "issue") for name in ("direct", "public")}
    operations = {
        "direct": lambda: direct_checkout(lab, box, qr, images["direct"]),
        "public": lambda: public_checkout(lab, qr, images["public"]),
    }
    loser = "public" if winner == "direct" else "direct"
    action = "admin_direct.checked_out" if winner == "direct" else "public_tool.checked_out"
    reached, release = pause_audit(monkeypatch, action)

    def committed_before_wait():
        stock(lab, 1, 0, 0)
        assert not PublicToolLoan.objects.filter(makerspace=lab.space).exists()
        quota(lab, 0)

    won, refused, pids, query = race(
        operations[winner], operations[loser], reached, release,
        table="makerspaces_makerspace", clause="FOR NO KEY UPDATE",
        before_second=committed_before_wait,
    )

    assert len(set(pids.values())) == 2
    assert 'FROM "makerspaces_makerspace"' in query and "FOR NO KEY UPDATE" in query
    assert won.status_code == 201, won.data
    assert refused.status_code in (400, 409), refused.data
    expected = "already checked out" if loser == "public" else "already out on another direct handout"
    # A QR-active refusal is also truthful for the public contender, before box resolution.
    assert expected in str(refused.data), refused.data
    loan = PublicToolLoan.objects.get(makerspace=lab.space)
    loan_trace(lab, loan, qr, images[winner], direct=winner == "direct", box=box)
    assert PublicToolLoan.objects.filter(container=box, status="checked_out").count() == 1
    assert HardwareRequest.objects.filter(makerspace=lab.space).count() == 1
    assert QrScanEvent.objects.filter(makerspace=lab.space).count() == 1
    assert not BoxScan.objects.filter(makerspace=lab.space).exists()
    assert not HardwareRequest.objects.filter(issue_evidence=images[loser]).exists()
    assert not AuditLog.objects.filter(
        makerspace=lab.space, action="evidence.attached", meta__evidence_id=images[loser].pk,
    ).exists()
    assert not AuditLog.objects.filter(
        makerspace=lab.space,
        action="public_tool.checked_out" if winner == "direct" else "admin_direct.checked_out",
    ).exists()
    finalized(lab, images[loser], charged=False)
    stock(lab, 0, 0, 1)
    quota(lab, 1)
    if winner == "direct":
        return_direct(lab, loan, qr)
    else:
        return_public(lab, qr)
    stock(lab, 1, 0, 0)
    quota(lab, 2)
    assert not PublicToolLoan.objects.filter(container=box, status="checked_out").exists()


@pytest.mark.parametrize("transport", ["post", "put"])
@pytest.mark.parametrize("winner", ["reviewed", "direct"])
def test_assigned_reviewed_box_vs_selected_container_units_waits_maker(
    monkeypatch, settings, transport, winner,
):
    # Reservation one plus TWO actual AVAILABLE units makes BOTH operations viable.
    # They scan different units; the common physical vessel is the intended conflict.
    lab = setup_lab(monkeypatch, settings, transport, individual=True, total=2)
    box, _box_qr = container(lab)
    reviewed = accept_and_assign(lab, box)
    assert list(reviewed.items.get().asset_links.all()) == []
    images = {name: photo(lab, lab.store, "issue") for name in ("reviewed", "direct")}
    operations = {
        "reviewed": lambda: reviewed_issue(lab, reviewed, lab.qrs[0], images["reviewed"]),
        # Deliberately no BOX QR: the container and explicitly scanned unit are separate.
        "direct": lambda: direct_checkout(lab, box, lab.qrs[1], images["direct"]),
    }
    loser = "direct" if winner == "reviewed" else "reviewed"
    reached, release = pause_audit(
        monkeypatch, "request.issued" if winner == "reviewed" else "admin_direct.checked_out",
    )

    def initial_state():
        stock(lab, 1, 1, 0)
        assert HardwareRequest.objects.get(pk=reviewed.pk).status == "accepted"
        assert not PublicToolLoan.objects.filter(makerspace=lab.space).exists()

    won, refused, _, query = race(
        operations[winner], operations[loser], reached, release,
        table="makerspaces_makerspace", clause="FOR NO KEY UPDATE", before_second=initial_state,
    )

    assert 'FROM "makerspaces_makerspace"' in query
    assert won.status_code == (200 if winner == "reviewed" else 201), won.data
    assert refused.status_code in (400, 409), refused.data
    assert ("already out on an issued request" if loser == "direct" else "Box is already out") in str(refused.data)
    reviewed.refresh_from_db()
    assert BoxScan.objects.filter(request=reviewed, box=box, context="issue").count() == 1
    assert QrScanEvent.objects.filter(makerspace=lab.space, context="issue").count() == 1
    assert AuditLog.objects.filter(action="box.assigned", target_id=str(reviewed.pk)).count() == 1
    assert AuditLog.objects.filter(action="request.accepted", target_id=str(reviewed.pk)).count() == 1
    assert not HardwareRequest.objects.filter(issue_evidence=images[loser]).exists()
    finalized(lab, images[loser], charged=False)
    quota(lab, 1)
    if winner == "direct":
        stock(lab, 0, 1, 1)
        assert reviewed.status == "accepted" and reviewed.issue_evidence_id is None
        assert not reviewed.items.get().asset_links.exists()
        assert not AuditLog.objects.filter(action="request.issued", target_id=str(reviewed.pk)).exists()
        loan = PublicToolLoan.objects.get(makerspace=lab.space)
        loan_trace(lab, loan, lab.qrs[1], images["direct"], direct=True, box=box, asset=lab.assets[1])
        return_direct(lab, loan, lab.qrs[1])
        stock(lab, 1, 1, 0)
        # The still-accepted reservation must remain usable after the vessel returns.
        retried = operations["reviewed"]()
        assert retried.status_code == 200, retried.data
        quota(lab, 3)
    else:
        stock(lab, 1, 0, 1)
        assert not PublicToolLoan.objects.filter(makerspace=lab.space).exists()
        assert not AuditLog.objects.filter(makerspace=lab.space, action="admin_direct.checked_out").exists()

    reviewed.refresh_from_db()
    assert reviewed.status == "issued" and reviewed.issue_evidence_id == images["reviewed"].pk
    item = reviewed.items.get()
    assert (item.accepted_quantity, item.issued_quantity, item.returned_quantity) == (1, 1, 0)
    link = item.asset_links.get()
    assert link.asset_id == lab.assets[0].pk and link.outcome == "issued"
    assert link.return_event_id is None
    scan = QrScanEvent.objects.get(request=reviewed, context="issue")
    assert scan.qr_code_id == lab.qrs[0].pk and scan.actor_id == lab.actor.pk
    assert AuditLog.objects.filter(action="asset.issued", target_id=str(lab.assets[0].pk)).count() == 1
    attached = AuditLog.objects.get(action="evidence.attached", target_id=str(images["reviewed"].pk))
    assert attached.meta["request_id"] == reviewed.pk and attached.actor_id == lab.actor.pk
    assert HardwareRequest.objects.filter(assigned_box=box, status="issued").count() == 1
    assert not PublicToolLoan.objects.filter(container=box, status="checked_out").exists()
    finalized(lab, images["reviewed"], charged=True)
    return_reviewed(lab, reviewed, box, lab.assets[0])
    stock(lab, 2, 0, 0)
    quota(lab, 4 if winner == "direct" else 2)
