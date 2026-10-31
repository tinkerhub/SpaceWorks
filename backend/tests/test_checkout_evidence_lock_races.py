"""Evidence/Maker inversion proofs at actual domain attachment boundaries."""
from datetime import timedelta
import threading

import pytest
from django.db import connection
from django.db.models.signals import post_save

from apps.audit.models import AuditLog
from apps.backup.models import DeploymentRecoveryState
from apps.boxes.models import QrScanEvent
from apps.evidence import services_retention, storage
from apps.evidence.models import (
    EvidenceObjectRetentionState, EvidencePhoto, EvidenceRetentionPolicy,
    EvidenceUploadFinalization,
)
from apps.hardware_requests import problem_report_workflow, self_checkout_workflow
from apps.hardware_requests.models import (
    HardwareRequest, PublicToolLoan, RequesterAccountability, ReturnEvent,
)
from tests.atomic_publication.store import png
from tests.checkout_lock_fixture_helpers import (
    client, finalized, product_qr, public_checkout, quota, return_public,
    returned_report, setup_lab, stock, triage,
)
from tests.checkout_lock_race_helpers import pause_attachment, prepared_race, prepare_validation
from tests.inventory_lending_evidence_helpers import photo

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("transport", ["post", "put"])
@pytest.mark.parametrize("winner", ["checkout", "triage"])
def test_triage_report_self_lock_then_shared_evidence_does_not_invert_maker(
    monkeypatch, settings, transport, winner,
):
    lab = setup_lab(monkeypatch, settings, transport)
    qr = product_qr(lab)
    report = returned_report(lab, qr)
    old_loan = report.loan
    old_request = old_loan.request
    old_return = old_loan.return_evidence_id
    shared = photo(lab, lab.store, "issue")
    assert not HardwareRequest.objects.filter(issue_evidence=shared).exists()
    quota(lab, 2)
    triage_locks = []

    def triaging():
        def capture(execute, sql, params, many, context):
            if "FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql:
                triage_locks.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(capture):
            return triage(lab, report, shared)

    operations = {
        "checkout": lambda: public_checkout(lab, qr, shared),
        "triage": triaging,
    }
    loser = "triage" if winner == "checkout" else "checkout"
    first_module = self_checkout_workflow if winner == "checkout" else problem_report_workflow
    second_module = problem_report_workflow if winner == "checkout" else self_checkout_workflow
    prepared, resume = prepare_validation(
        monkeypatch, second_module, label="Triage" if loser == "triage" else "Issue",
    )
    reached, release = pause_attachment(monkeypatch, first_module, shared.pk)

    first, second, pids, query = prepared_race(
        operations[winner], operations[loser], reached, release, prepared, resume,
        table="evidence_evidencephoto", clause="FOR UPDATE",
    )

    # Checkout-first is the inversion proof: checkout owns Evidence but has not
    # called Maker guard; triage has already validated/promoted, locks only its
    # report self row and waits on attachment Evidence. An old joined Maker lock
    # would deadlock when checkout resumes. Reverse order proves safe shared use
    # and exactly-once charging, rather than claiming a second opposing cycle.
    assert len(set(pids.values())) == 2 and 'FROM "evidence_evidencephoto"' in query
    assert [first.status_code, second.status_code] == ([201, 200] if winner == "checkout" else [200, 201])
    report_index = next(i for i, sql in enumerate(triage_locks)
                        if 'FROM "hardware_requests_publicproblemreport"' in sql)
    assert 'FOR UPDATE OF "hardware_requests_publicproblemreport"' in triage_locks[report_index]
    domain_locks = triage_locks[report_index + 1:]
    evidence_index = next(i for i, sql in enumerate(domain_locks)
                          if 'FROM "evidence_evidencephoto"' in sql)
    maker_index = next(i for i, sql in enumerate(domain_locks)
                       if 'FROM "makerspaces_makerspace"' in sql)
    assert evidence_index < maker_index
    assert "FOR NO KEY UPDATE" in domain_locks[maker_index]
    report.refresh_from_db()
    assert report.outcome == "no_issue" and report.resolved_at is not None
    assert report.resolved_by_id == lab.actor.pk and report.triage_note == "Inspected; no defect"
    entry = AuditLog.objects.get(makerspace=lab.space, action="problem_report.triaged")
    assert entry.actor_id == lab.actor.pk and entry.target_id == str(report.pk)
    assert entry.meta == {
        "outcome": "no_issue", "quantities": [], "loan_id": old_loan.pk,
        "request_id": old_request.pk, "evidence_id": shared.pk,
    }
    assert not RequesterAccountability.objects.filter(makerspace=lab.space).exists()
    assert not AuditLog.objects.filter(
        makerspace=lab.space, action__in=["item.damaged", "item.missing"],
    ).exists()
    old_loan.refresh_from_db()
    old_request.refresh_from_db()
    assert old_loan.status == old_request.status == "returned"
    assert old_loan.return_evidence_id == old_return
    new = PublicToolLoan.objects.get(makerspace=lab.space, status="checked_out")
    assert new.request.issue_evidence_id == shared.pk and new.pk != old_loan.pk
    assert new.qr_ids == [qr.pk] and new.request.items.get().issued_quantity == 1
    assert new.request.items.get().returned_quantity == 0
    assert QrScanEvent.objects.filter(request=new.request, qr_code=qr, context="issue").count() == 1
    assert AuditLog.objects.filter(action="public_tool.checked_out", target_id=str(new.request_id)).count() == 1
    finalized(lab, shared, charged=True)
    stock(lab, 0, 0, 1)
    quota(lab, 3)  # Two genuine old-loan images + one shared image, never four.
    return_public(lab, qr)
    stock(lab, 1, 0, 0)
    quota(lab, 4)


@pytest.mark.parametrize("transport", ["post", "put"])
def test_public_return_waits_attachment_evidence_without_maker_while_real_sweep_finishes(
    monkeypatch, settings, transport,
):
    lab = setup_lab(monkeypatch, settings, transport)
    # Create this photo FIRST; a future as_of cutoff selects it alone without
    # mutating any immutable created_at or manufacturing an EXPIRING state.
    candidate = photo(lab, lab.store, "return")
    metadata = EvidencePhoto.objects.filter(pk=candidate.pk).values().get()
    qr = product_qr(lab)
    report = returned_report(lab, qr)
    # Triage genuinely accepts RETURN evidence. It charges this otherwise-unused
    # return image via the actual endpoint, so PUT expiry must execute free_storage.
    # Neither a ReturnEvent nor a loan's return_evidence has consumed it.
    resolved = triage(lab, report, candidate)
    assert resolved.status_code == 200, resolved.data
    assert not PublicToolLoan.objects.filter(return_evidence=candidate).exists()
    assert not ReturnEvent.objects.filter(evidence=candidate).exists()
    issue = photo(lab, lab.store, "issue")
    checked_out = public_checkout(lab, qr, issue)
    assert checked_out.status_code == 201, checked_out.data
    active = PublicToolLoan.objects.get(makerspace=lab.space, status="checked_out")
    quota(lab, 4)
    finalized(lab, candidate, charged=True)
    EvidenceRetentionPolicy.objects.create(makerspace=lab.space, object_retention_days=30)
    recovery = DeploymentRecoveryState.load()
    assert recovery.mode == "normal"
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    as_of = candidate.created_at + timedelta(days=30)
    assert issue.created_at > candidate.created_at
    reached, release, preflight_done = threading.Event(), threading.Event(), threading.Event()
    preflight = self_checkout_workflow.preflight_public_return

    def observe_preflight(*args, **kwargs):
        result = preflight(*args, **kwargs)
        preflight_done.set()
        return result

    monkeypatch.setattr(self_checkout_workflow, "preflight_public_return", observe_preflight)
    prepared, resume = prepare_validation(monkeypatch, self_checkout_workflow, label="Return")

    def expired_saved(sender, instance, **kwargs):
        if instance.evidence_id == candidate.pk and instance.status == "expired":
            # Real claim + strict two-key version deletion have finished. _complete
            # owns Evidence; its actual Maker free_storage UPDATE is the next step.
            assert connection.in_atomic_block and prepared.is_set() and preflight_done.is_set()
            assert candidate.object_key not in lab.store.objects
            assert storage.staging_key(candidate.object_key) not in lab.store.objects
            reached.set()
            assert release.wait(12), "Retention completion checkpoint was not released"

    def returning():
        return client(lab).post(f"/api/v1/public/{lab.space.slug}/tools/return", {
            "payload": qr.payload, "evidence_id": candidate.pk,
            "remark": "Inspected at return",
        }, format="json")

    post_save.connect(expired_saved, sender=EvidenceObjectRetentionState, weak=False)
    try:
        summary, refused, pids, query = prepared_race(
            lambda: services_retention.sweep_evidence_retention(now=as_of, batch_size=1),
            returning, reached, release, prepared, resume,
            table="evidence_evidencephoto", clause="FOR UPDATE",
        )
    finally:
        post_save.disconnect(expired_saved, sender=EvidenceObjectRetentionState)

    assert len(set(pids.values())) == 2 and 'FROM "evidence_evidencephoto"' in query
    assert summary["photos_claimed"] == summary["photos_expired"] == 1
    assert summary["photos_eligible"] == 1 and summary["photos_failed"] == 0
    assert summary["bytes_removed"] == len(png()) and not summary["continuation_required"]
    assert refused.status_code == 400, refused.data
    assert refused.data["code"] == "return_validation_error"
    assert "expired under the retention policy" in str(refused.data)
    state = EvidenceObjectRetentionState.objects.get(evidence=candidate)
    assert state.status == "expired" and state.claim_token is None
    assert state.expired_size_bytes == len(png()) and state.object_expired_at is not None
    assert EvidencePhoto.objects.filter(pk=candidate.pk).values().get() == metadata
    assert not lab.store.versions.get(candidate.object_key)
    assert not lab.store.versions.get(storage.staging_key(candidate.object_key))
    assert any(name == "delete" for name, _ in lab.store.calls)
    expiration = AuditLog.objects.get(action="evidence.object_expired", target_id=str(candidate.pk))
    assert expiration.meta["expired_size_bytes"] == len(png())
    assert expiration.meta["final_outcome"] == "deleted"
    active.refresh_from_db()
    assert active.status == "checked_out"
    assert active.request.status == "issued" and active.return_evidence_id is None
    assert active.request.items.get().returned_quantity == 0
    assert not ReturnEvent.objects.filter(request=active.request).exists()
    assert not PublicToolLoan.objects.filter(return_evidence=candidate).exists()
    assert not ReturnEvent.objects.filter(evidence=candidate).exists()
    assert not AuditLog.objects.filter(
        action="evidence.attached", target_id=str(candidate.pk), meta__request_id=active.request_id,
    ).exists()
    assert not QrScanEvent.objects.filter(request=active.request, context="return").exists()
    assert not AuditLog.objects.filter(action="public_tool.returned", target_id=str(active.request_id)).exists()
    stock(lab, 0, 0, 1)
    lab.space.refresh_from_db()
    assert lab.space.storage_bytes_used == (3 * len(png()) if transport == "put" else 0)
    # A later legitimate image completes the same outstanding loan normally.
    return_public(lab, qr)
    stock(lab, 1, 0, 0)
    lab.space.refresh_from_db()
    assert lab.space.storage_bytes_used == (4 * len(png()) if transport == "put" else 0)
    assert EvidenceUploadFinalization.objects.filter(
        evidence__makerspace=lab.space, quota_charged=True,
    ).count() == (5 if transport == "put" else 0)
