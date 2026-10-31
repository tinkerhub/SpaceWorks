"""EVID-S07: permanent provider failures cannot monopolize a bounded sweep."""
from datetime import timedelta
from unittest.mock import patch

import pytest

from apps.backup.models import DeploymentRecoveryState
from apps.evidence import finalization, storage
from apps.evidence.models import EvidenceObjectRetentionState
from apps.evidence.retention_policy import object_candidates
from apps.evidence.services_retention import _claim, sweep_evidence_retention
from apps.tenant_migration import source_gate
from tests.atomic_publication.store import png
from tests.evidence.safety_retention_helpers import (
    expiry_events, fail_deletes, metadata, photo, safety_lab, usage,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("failed_key", ["final", "staging"], ids=["final-delete-fails", "staging-after-final-fails"])
def test_second_bounded_sweep_progresses_past_first_batch_permanent_failures(
    monkeypatch, settings, failed_key,
):
    lab = safety_lab(monkeypatch, settings)
    batch = 3
    born = lab.now - timedelta(days=40)
    evidence = [photo(lab, charged=True, created_at=born) for _ in range(batch * 2)]
    failed, good = evidence[:batch], evidence[batch:]
    before = {row.pk: metadata(row) for row in evidence}
    for row in evidence:
        lab.store.seed(storage.staging_key(row.object_key), png(), "image/png")
    keys = {row.object_key if failed_key == "final" else storage.staging_key(row.object_key)
            for row in failed}
    fail_deletes(lab.store, keys)
    lab.store.calls.clear()

    first = sweep_evidence_retention(now=lab.now, batch_size=batch)

    assert first == {
        "makerspaces_scanned": 1, "makerspaces_skipped": 0, "photos_eligible": batch,
        "photos_claimed": batch, "photos_expired": 0, "photos_failed": batch,
        "bytes_removed": 0, "continuation_required": True,
    }
    assert not any(expiry_events(row).exists() for row in evidence)
    assert usage(lab) == len(png()) * batch * 2
    attempted = {item["Key"] for call, kwargs in lab.store.calls if call == "delete"
                 for item in kwargs["Delete"]["Objects"]}
    assert attempted <= {key for row in failed for key in (
        row.object_key, storage.staging_key(row.object_key),
    )}
    for row in failed:
        state = EvidenceObjectRetentionState.objects.get(evidence=row)
        assert state.status == "expiring" and state.claim_token is None
        assert state.object_expired_at is None and state.last_error
        if failed_key == "staging":
            assert not lab.store.versions[row.object_key]
            assert lab.store.versions[storage.staging_key(row.object_key)]
        else:
            assert lab.store.versions[row.object_key]
    assert not EvidenceObjectRetentionState.objects.filter(evidence__in=good).exists()
    lab.store.calls.clear()

    second = sweep_evidence_retention(now=lab.now, batch_size=batch)

    assert second == {
        "makerspaces_scanned": 1, "makerspaces_skipped": 0, "photos_eligible": batch,
        "photos_claimed": batch, "photos_expired": batch, "photos_failed": 0,
        "bytes_removed": len(png()) * batch, "continuation_required": True,
    }
    assert usage(lab) == len(png()) * batch
    for row in failed:
        assert not expiry_events(row).exists()
        state = EvidenceObjectRetentionState.objects.get(evidence=row)
        assert state.status == "expiring" and state.object_expired_at is None
    for row in good:
        state = EvidenceObjectRetentionState.objects.get(evidence=row)
        assert state.status == "expired" and state.claim_token is None
        assert expiry_events(row).get().meta["quota_released_bytes"] == len(png())
        assert not lab.store.versions[row.object_key]
        assert not lab.store.versions[storage.staging_key(row.object_key)]
    assert {row.pk: metadata(row) for row in evidence} == before
    third = sweep_evidence_retention(now=lab.now, batch_size=batch)
    assert third["photos_claimed"] == third["photos_failed"] == batch
    assert third["photos_expired"] == third["bytes_removed"] == 0
    assert third["continuation_required"] is False  # exactly one remaining batch
    assert usage(lab) == len(png()) * batch


def test_stable_ties_and_existing_retries_order_by_oldest_state_attempt(monkeypatch, settings):
    lab = safety_lab(monkeypatch, settings)
    born = lab.now - timedelta(days=40)
    rows = [photo(lab, charged=True, created_at=born) for _ in range(4)]
    before = {row.pk: metadata(row) for row in rows}
    # State clocks model real earlier attempts, without touching photo metadata.
    for row, hours in ((rows[0], 1), (rows[1], 3)):
        with patch("django.utils.timezone.now", return_value=lab.now - timedelta(hours=hours)):
            EvidenceObjectRetentionState.objects.create(evidence=row, last_error="earlier attempt")
    candidates, _, _ = object_candidates(lab.space, as_of=lab.now)
    assert list(candidates.values_list("pk", flat=True)) == [
        rows[2].pk, rows[3].pk, rows[1].pk, rows[0].pk,
    ]
    first = sweep_evidence_retention(now=lab.now, batch_size=2)
    assert first["photos_expired"] == 2 and first["continuation_required"] is True
    fail_deletes(lab.store, {rows[1].object_key})
    attempted_before = EvidenceObjectRetentionState.objects.get(evidence=rows[1]).updated_at
    second = sweep_evidence_retention(now=lab.now, batch_size=1)
    assert second["photos_failed"] == 1 and second["continuation_required"] is True
    assert EvidenceObjectRetentionState.objects.get(evidence=rows[1]).updated_at > attempted_before
    third = sweep_evidence_retention(now=lab.now, batch_size=1)
    assert third["photos_expired"] == 1  # newer creation, but older last retry
    assert expiry_events(rows[0]).count() == 1 and not expiry_events(rows[1]).exists()
    assert {row.pk: metadata(row) for row in rows} == before


def test_retry_timestamp_ties_fall_back_to_photo_creation_then_pk(monkeypatch, settings):
    lab = safety_lab(monkeypatch, settings)
    born = lab.now - timedelta(days=40)
    rows = [photo(lab, created_at=born), photo(lab, created_at=born), photo(lab, days=41)]
    before = {row.pk: metadata(row) for row in rows}
    for row in reversed(rows):
        with patch("django.utils.timezone.now", return_value=lab.now - timedelta(hours=1)):
            EvidenceObjectRetentionState.objects.create(evidence=row)
    candidates, _, _ = object_candidates(lab.space, as_of=lab.now)
    assert list(candidates.values_list("pk", flat=True)) == [rows[2].pk, rows[0].pk, rows[1].pk]
    assert {row.pk: metadata(row) for row in rows} == before


@pytest.mark.parametrize("guard", ["promoting", "lease", "source-frozen", "recovery"])
def test_fair_ordering_preserves_busy_and_global_source_fences(monkeypatch, settings, guard):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, finalized=guard != "promoting", charged=guard != "promoting")
    before = metadata(evidence)
    charged = usage(lab)
    if guard == "promoting":
        token, completed = finalization._claim(evidence.pk)
        assert token is not None and completed is None
    elif guard == "lease":
        claim = _claim(evidence.pk, now=lab.now)
        assert claim is not None
    elif guard == "source-frozen":
        source_gate.claim(lab.space, lab.actor)
    else:
        state = DeploymentRecoveryState.load()
        state.mode = DeploymentRecoveryState.Mode.QUIESCED
        state.save(update_fields=["mode", "updated_at"])
    calls = list(lab.store.calls)

    result = sweep_evidence_retention(now=lab.now, batch_size=1)

    assert result["photos_claimed"] == result["photos_expired"] == result["photos_failed"] == 0
    assert result["bytes_removed"] == 0
    assert result["makerspaces_skipped"] == int(guard in {"source-frozen", "recovery"})
    assert lab.store.calls == calls and usage(lab) == charged
    assert metadata(evidence) == before and not expiry_events(evidence).exists()
    if guard != "lease":
        assert not EvidenceObjectRetentionState.objects.filter(evidence=evidence).exists()


@pytest.mark.parametrize("requested_batch", [0, -40])
def test_nonpositive_batch_is_clamped_and_work_stays_bounded(monkeypatch, settings, requested_batch):
    lab = safety_lab(monkeypatch, settings)
    rows = [photo(lab, charged=True) for _ in range(2)]
    result = sweep_evidence_retention(now=lab.now, batch_size=requested_batch)
    assert result["photos_eligible"] == result["photos_claimed"] == result["photos_expired"] == 1
    assert result["continuation_required"] is True
    assert sum(expiry_events(row).count() for row in rows) == 1
    assert usage(lab) == len(png())
