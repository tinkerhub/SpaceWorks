"""EVID-S03: only an exact deployment-local journal debit may release quota."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import DatabaseError, transaction
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.evidence import finalization, storage
from apps.evidence.models import EvidenceObjectRetentionState, EvidenceUploadFinalization
from apps.evidence.quota import finalized_size_bytes, proven_charge_bytes
from apps.evidence.services_retention import sweep_evidence_retention
from apps.makerspaces import limits
from tests.atomic_publication.store import png
from tests.evidence.safety_retention_helpers import (
    expiry_events, historical_unproved_charge, journal, markers, metadata, photo,
    remove_identity_for_missing_infrastructure_case, safety_lab, usage,
)
from tests.return_helpers import make_space


pytestmark = pytest.mark.django_db(transaction=True)


def test_real_finite_put_debit_emits_one_immutable_scoped_marker(monkeypatch, settings):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, finalized=True)
    before = metadata(evidence)
    finalization.charge_storage_once(evidence, len(png()))
    state = journal(evidence)
    event = markers(evidence).get()
    assert event.meta == {
        "version": 1, "bytes": len(png()), "journal_version": state.updated_at.isoformat(),
        "accounting_database_id": str(DeploymentDatabaseIdentity.load().database_uuid),
    }
    assert state.quota_charged is True and usage(lab) == len(png())
    finalization.charge_storage_once(evidence, len(png()))
    assert markers(evidence).count() == 1 and usage(lab) == len(png())
    assert journal(evidence).updated_at == state.updated_at
    assert metadata(evidence) == before
    with pytest.raises(DatabaseError), transaction.atomic():
        markers(evidence).update(meta={})
    assert markers(evidence).get().meta == event.meta
    with pytest.raises(DatabaseError), transaction.atomic():
        markers(evidence).delete()
    assert markers(evidence).count() == 1


@pytest.mark.parametrize("mode", ["selfhost", "unlimited", "zero", "post"])
def test_real_quota_noops_do_not_emit_marker_or_set_handled(monkeypatch, settings, mode):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, finalized=True)
    if mode == "selfhost":
        settings.PLATFORM_DOMAIN_SUFFIX = ""
    elif mode == "unlimited":
        lab.space.resource_limit_overrides = {"storage": None}
        lab.space.save(update_fields=["resource_limit_overrides"])
    elif mode == "post":
        settings.STORAGE_PRESIGN_METHOD = "post"
    if mode == "zero":
        assert limits.add_storage(lab.space, 0) is False
    else:
        if mode != "post":
            assert limits.add_storage(lab.space, len(png())) is False
        finalization.charge_storage_once(evidence, len(png()))
    assert usage(lab) == 0 and not markers(evidence).exists()
    assert journal(evidence).quota_charged is False


@pytest.mark.parametrize("handled", [False, True], ids=["unhandled", "legacy-handled"])
@pytest.mark.parametrize("case", ["pending", "promoting", "zero", "mismatch", "bool", "float", "none", "zero-arg", "negative-arg"])
def test_producer_refuses_invalid_journal_or_size_before_debit(monkeypatch, settings, handled, case):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, finalized=True)
    state = journal(evidence)
    # Historical handled=True is explicitly unproved; it must not bypass validation.
    state.quota_charged = handled
    if case in {"pending", "promoting"}:
        state.status = case
    elif case == "zero":
        state.size_bytes = 0
    state.save()
    supplied = {"mismatch": len(png()) + 1, "bool": True, "zero-arg": 0, "negative-arg": -1,
                "float": float(len(png())), "none": None}.get(case, len(png()))
    before = EvidenceUploadFinalization.objects.values().get(evidence=evidence)
    with pytest.raises(ValidationError) as exc:
        finalization.charge_storage_once(evidence, supplied)
    assert exc.value.get_codes() == {"size_bytes": "invalid_evidence_size"}
    assert usage(lab) == 0 and not markers(evidence).exists()
    assert EvidenceUploadFinalization.objects.values().get(evidence=evidence) == before


@pytest.mark.parametrize("field,value", [
    ("version", True), ("version", 1.0), ("version", 2),
    ("bytes", True), ("bytes", float(len(png()))), ("bytes", len(png()) + 1),
    ("journal_version", "stale"), ("journal_version", None),
    ("journal_version", True),
    pytest.param("accounting_database_id", str(uuid4()), id="foreign-database-uuid"),
    ("accounting_database_id", "source-local"),
    ("accounting_database_id", None),
])
def test_verifier_rejects_historical_unproved_marker_fields(monkeypatch, settings, field, value):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, finalized=True)
    if value == "source-local":
        value = f"source:{DeploymentDatabaseIdentity.load().database_uuid}"
    historical_unproved_charge(evidence, meta_changes={field: value})
    assert proven_charge_bytes(evidence, journal(evidence)) == 0
    result = sweep_evidence_retention(now=lab.now, batch_size=1)
    assert result["photos_expired"] == 1
    assert usage(lab) == len(png())
    assert expiry_events(evidence).get().meta["quota_released_bytes"] == 0


@pytest.mark.parametrize("wrong_scope", ["maker", "evidence", "target-type"])
def test_verifier_rejects_other_maker_or_evidence_marker(monkeypatch, settings, wrong_scope):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, finalized=True)
    other = make_space(f"other-{uuid4().hex[:10]}")
    target = photo(lab, days=0) if wrong_scope == "evidence" else None
    historical_unproved_charge(
        evidence, scope=other if wrong_scope == "maker" else None,
        target=other if wrong_scope == "target-type" else target,
    )
    assert proven_charge_bytes(evidence, journal(evidence)) == 0
    assert usage(lab) == len(png())
    other_journal = journal(photo(lab, finalized=True, days=0))
    assert proven_charge_bytes(evidence, other_journal) == 0


@pytest.mark.parametrize("size", [True, 1.0, 0, -1, None])
def test_verifier_does_not_coerce_untrusted_journal_sizes(size):
    assert finalized_size_bytes(SimpleNamespace(status="finalized", size_bytes=size)) == 0


def test_same_deployment_consistent_metadata_keeps_one_proof_never_sums_markers(monkeypatch, settings):
    """Metadata/counter consistency only; this does not exercise a host restore."""
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, charged=True)
    state = journal(evidence)
    marker = markers(evidence).get()
    audit.record(None, "evidence.storage_charged", makerspace=lab.space,
                 target=evidence, meta=marker.meta)
    assert proven_charge_bytes(evidence, state) == len(png())
    assert usage(lab) == len(png()) and markers(evidence).count() == 2
    assert sweep_evidence_retention(now=lab.now, batch_size=1)["photos_expired"] == 1
    assert usage(lab) == 0
    assert expiry_events(evidence).get().meta["quota_released_bytes"] == len(png())
    assert sweep_evidence_retention(now=lab.now, batch_size=1)["photos_expired"] == 0
    assert expiry_events(evidence).count() == 1 and usage(lab) == 0


def test_genuine_marker_does_not_follow_a_changed_journal_version(monkeypatch, settings):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, charged=True)
    state = journal(evidence)
    assert proven_charge_bytes(evidence, state) == len(png())
    old_stamp = markers(evidence).get().meta["journal_version"]
    state.save(update_fields=["updated_at"])
    assert state.updated_at.isoformat() != old_stamp
    assert proven_charge_bytes(evidence, state) == 0
    assert markers(evidence).get().meta["journal_version"] == old_stamp


@pytest.mark.parametrize("provision_later", [False, True], ids=["still-missing", "later-provisioned"])
def test_missing_identity_debits_but_cannot_later_gain_automatic_credit(monkeypatch, settings, provision_later):
    lab = safety_lab(monkeypatch, settings, seed_identity=False)
    remove_identity_for_missing_infrastructure_case()
    evidence = photo(lab, finalized=True)
    assert limits.add_storage(lab.space, 113) is True  # unrelated real usage
    finalization.charge_storage_once(evidence, len(png()))
    assert markers(evidence).get().meta["accounting_database_id"] is None
    assert not DeploymentDatabaseIdentity.objects.exists()  # source never seeds it
    assert usage(lab) == 113 + len(png())
    if provision_later:
        DeploymentDatabaseIdentity.load()  # later infrastructure provisioning is not proof
    assert proven_charge_bytes(evidence, journal(evidence)) == 0
    assert sweep_evidence_retention(now=lab.now, batch_size=1)["photos_expired"] == 1
    assert usage(lab) == 113 + len(png())
    assert expiry_events(evidence).get().meta["quota_released_bytes"] == 0
    assert DeploymentDatabaseIdentity.objects.exists() is provision_later


@pytest.mark.parametrize("legacy", [False, True], ids=["missing-photo-no-journal", "legacy-true-no-proof"])
def test_declared_size_and_legacy_handled_flag_cannot_free_other_storage(monkeypatch, settings, legacy):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, declared=2**50, uploaded=False)
    before = metadata(evidence)
    if legacy:
        EvidenceUploadFinalization.objects.create(
            evidence=evidence, status="finalized", size_bytes=len(png()), quota_charged=True,
        )  # explicitly historical/unproved; no debit or marker ever existed
    assert limits.add_storage(lab.space, 509) is True
    result = sweep_evidence_retention(now=lab.now, batch_size=1)
    assert result["photos_expired"] == 1
    assert result["bytes_removed"] == (len(png()) if legacy else 0)
    assert usage(lab) == 509 and not markers(evidence).exists()
    assert expiry_events(evidence).get().meta["quota_released_bytes"] == 0
    assert metadata(evidence) == before


def test_strict_all_version_deletion_precedes_proven_journal_release(monkeypatch, settings):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, declared=2**50, charged=True)
    before = metadata(evidence)
    charged = usage(lab)
    final, staged = evidence.object_key, storage.staging_key(evidence.object_key)
    for key in (final, staged):
        lab.store.seed(key, png("red"), "image/png")
        lab.store.seed(key, png() + b"retained version padding", "image/png")
        lab.store.markers[key] = {f"marker-{key}"}
    observed_size = len(png()) + len(b"retained version padding")
    assert observed_size != charged
    settings.STORAGE_PRESIGN_METHOD = "post"  # current transport cannot erase a prior debit
    checkpoints = []

    def before_delete(kwargs):
        checkpoints.append(kwargs["Delete"]["Objects"])
        assert EvidenceObjectRetentionState.objects.get(evidence=evidence).status == "expiring"
        assert usage(lab) == charged and not expiry_events(evidence).exists()
    lab.store.before_delete = before_delete
    result = sweep_evidence_retention(now=lab.now, batch_size=1)
    assert len(checkpoints) == 2
    assert all(not lab.store.versions[key] and not lab.store.markers[key] for key in (final, staged))
    assert result["photos_expired"] == 1 and result["bytes_removed"] == observed_size
    event = expiry_events(evidence).get()
    assert event.meta["expired_size_bytes"] == observed_size
    assert event.meta["quota_released_bytes"] == charged == len(png())
    assert usage(lab) == 0 and metadata(evidence) == before
    assert sweep_evidence_retention(now=lab.now, batch_size=1)["photos_expired"] == 0
    assert expiry_events(evidence).count() == 1 and usage(lab) == 0
