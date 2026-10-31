"""EVID-S02: a candidate snapshot cannot authorize deletion under stale policy."""
from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import reverse

from apps.evidence import storage
from apps.evidence.models import EvidenceObjectRetentionState
from apps.evidence.retention_policy import object_candidates, update_policy
from apps.evidence.services_retention import _claim, _complete, sweep_evidence_retention
from tests.evidence.safety_retention_helpers import (
    expiry_events, fail_deletes, metadata, photo, safety_lab, usage,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("via_patch", [True, False], ids=["policy-PATCH", "policy-service"])
def test_old_candidate_snapshot_cannot_claim_after_committed_extension(
    monkeypatch, settings, via_patch,
):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, charged=True)
    before = metadata(evidence)
    charged = usage(lab)
    candidates, days, _ = object_candidates(lab.space, as_of=lab.now)
    old_ids = list(candidates.values_list("pk", flat=True))
    assert old_ids == [evidence.pk] and days == 30
    if via_patch:
        response = lab.client.patch(reverse(
            "evidence_admin:evidence-retention-policy",
            kwargs={"makerspace_id": lab.space.pk},
        ), {"object_retention_days": 90}, format="json")
        assert response.status_code == 200, response.data
        assert response.data["effective_days"] == 90
    else:
        assert update_policy(lab.space, lab.actor, 90)["effective_days"] == 90
    calls = list(lab.store.calls)

    assert _claim(old_ids[0], now=lab.now) is None

    assert lab.store.calls == calls
    assert not EvidenceObjectRetentionState.objects.filter(evidence=evidence).exists()
    assert not expiry_events(evidence).exists()
    assert usage(lab) == charged
    assert metadata(evidence) == before


def test_committed_claim_can_finish_using_its_actual_policy_after_extension(monkeypatch, settings):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, charged=True)
    before = metadata(evidence)
    update_policy(lab.space, lab.actor, 35)
    claim = _claim(evidence.pk, now=lab.now)
    assert claim.policy_days == 35
    assert claim.cutoff == lab.now - timedelta(days=35)
    update_policy(lab.space, lab.actor, 90)
    size = storage.object_size(evidence.object_key)
    outcomes = {
        "final": storage.delete_object_strict(evidence.object_key),
        "staging": storage.delete_object_strict(storage.staging_key(evidence.object_key)),
    }

    assert _complete(claim, size=size, outcomes=outcomes, run_id=uuid4()) == size

    event = expiry_events(evidence).get()
    assert event.meta["policy_days"] == 35
    assert event.meta["cutoff"] == claim.cutoff.isoformat()
    assert usage(lab) == 0
    assert metadata(evidence) == before


def test_retry_rechecks_policy_and_audits_the_retry_cutoff(monkeypatch, settings):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, charged=True)
    before = metadata(evidence)
    fail_deletes(lab.store, {evidence.object_key})
    failed = sweep_evidence_retention(now=lab.now, batch_size=1)
    assert failed["photos_failed"] == 1 and not expiry_events(evidence).exists()
    update_policy(lab.space, lab.actor, 35)
    lab.store.before_delete = None

    retried = sweep_evidence_retention(now=lab.now, batch_size=1)

    assert retried["photos_expired"] == 1
    event = expiry_events(evidence).get()
    assert event.meta["policy_days"] == 35
    assert event.meta["cutoff"] == (lab.now - timedelta(days=35)).isoformat()
    assert metadata(evidence) == before


def test_extension_after_partial_delete_preserves_expiring_attachment_fence(monkeypatch, settings):
    from apps.evidence.finalization import lock_evidence_for_attachment
    from django.db import transaction

    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, charged=True)
    staged = storage.staging_key(evidence.object_key)
    lab.store.seed(staged, b"late upload", "image/png")
    fail_deletes(lab.store, {staged})
    first = sweep_evidence_retention(now=lab.now, batch_size=1)
    assert first["photos_failed"] == 1
    assert not lab.store.versions[evidence.object_key]
    before = metadata(evidence)
    counter = usage(lab)
    update_policy(lab.space, lab.actor, 90)
    lab.store.before_delete = None
    calls = list(lab.store.calls)

    assert _claim(evidence.pk, now=lab.now) is None
    second = sweep_evidence_retention(now=lab.now, batch_size=1)

    assert second["photos_claimed"] == second["photos_expired"] == 0
    state = EvidenceObjectRetentionState.objects.get(evidence=evidence)
    assert state.status == "expiring" and state.object_expired_at is None
    assert state.claim_token is None and state.last_error
    with transaction.atomic():
        assert lock_evidence_for_attachment(evidence.pk) is False
    assert lab.store.calls == calls
    assert usage(lab) == counter and not expiry_events(evidence).exists()
    assert metadata(evidence) == before
