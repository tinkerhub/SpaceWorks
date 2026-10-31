"""Live/snapshot report scopes use retained expiry state, never provider presence."""

from datetime import date

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.evidence import storage
from apps.evidence.models import EvidenceObjectRetentionState
from tests.evidence.report_object_expiry_helpers import (
    CREATED, assert_metrics, attachment_snapshot, historical, instant,
    metadata_snapshot, report_lab,
)
from tests.return_helpers import make_space


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", ["issue", "return"])
def test_unrolled_sweep_changes_only_object_counts(report_lab, kind):
    lab = report_lab
    photo = lab.photo(kind=kind, size=31, attached=True)
    before = lab.report()
    metadata = metadata_snapshot(lab.space)
    attachments = attachment_snapshot(lab.space)
    assert_metrics(before.records[0], created=1, attached=1, size=31, expired=0)

    summary = lab.sweep()

    assert summary["photos_expired"] == 1
    assert summary["photos_failed"] == 0
    state = EvidenceObjectRetentionState.objects.get(evidence=photo)
    assert state.status == EvidenceObjectRetentionState.Status.EXPIRED
    assert state.object_expired_at is not None
    assert state.claim_token is None and state.claimed_at is None
    assert state.expired_size_bytes == 31
    keys = (photo.object_key, storage.staging_key(photo.object_key))
    assert [key for op, key in lab.store.calls if op == "delete"] == list(keys)
    assert all(key not in lab.store.objects for key in keys)
    after = lab.report()
    assert after.meta["source"] == "live"
    assert after.meta["rollup_through"] is None
    assert after.records[0]["evidence_type"] == kind
    assert after.records[0]["period"] == date(2026, 2, 1)
    assert_metrics(after.records[0], created=1, attached=1, size=31, expired=1)
    assert historical(after.records) == historical(before.records)
    assert metadata_snapshot(lab.space) == metadata
    assert attachment_snapshot(lab.space) == attachments
    assert AuditLog.objects.filter(action="evidence.object_expired").count() == 1


def test_failed_staging_delete_is_expiring_until_real_retry_completes(report_lab):
    lab = report_lab
    photo = lab.photo(size=29)
    staged = storage.staging_key(photo.object_key)
    lab.store.fail_deletes.add(staged)
    metadata = metadata_snapshot(lab.space)

    failed = lab.sweep()

    assert failed["photos_failed"] == 1 and failed["photos_expired"] == 0
    state = EvidenceObjectRetentionState.objects.get(evidence=photo)
    assert state.status == EvidenceObjectRetentionState.Status.EXPIRING
    assert state.object_expired_at is None
    assert state.claim_token is None and state.claimed_at is None
    assert "StorageUnavailable" in state.last_error
    assert photo.object_key not in lab.store.objects and staged in lab.store.objects
    assert_metrics(lab.report().records[0], created=1, attached=0, size=29, expired=0)
    assert not AuditLog.objects.filter(action="evidence.object_expired").exists()

    lab.store.fail_deletes.clear()
    retried = lab.sweep()
    assert retried["photos_expired"] == 1 and retried["bytes_removed"] == 29
    assert_metrics(lab.report().records[0], created=1, attached=0, size=29, expired=1)
    assert metadata_snapshot(lab.space) == metadata
    calls = list(lab.store.calls)
    assert lab.sweep()["photos_expired"] == 0
    assert lab.store.calls == calls
    assert AuditLog.objects.filter(action="evidence.object_expired").count() == 1


@pytest.mark.parametrize("rolled", [False, True], ids=["live", "rolled"])
def test_exact_local_date_type_and_tenant_scope(report_lab, rolled):
    lab = report_lab
    other = make_space("expiry-date-other")
    lab.photo(when=instant("2026-01-31T18:29:59+00:00"), size=101)
    lab.photo(when=instant("2026-01-31T18:30:00+00:00"), size=11, attached=True)
    retrying = lab.photo(when=instant("2026-02-01T02:00:00+00:00"), size=13)
    lab.photo(when=instant("2026-02-01T04:00:00+00:00"), kind="return", size=19, attached=True)
    lab.photo(when=instant("2026-02-01T18:30:00+00:00"), size=103)
    lab.photo(space=other, size=107)
    if rolled:
        lab.roll()
        lab.roll(space=other)
    lab.store.fail_deletes.add(storage.staging_key(retrying.object_key))
    summary = lab.sweep()
    assert summary["photos_expired"] == 5 and summary["photos_failed"] == 1

    result = lab.report(date_range=(
        instant("2026-02-01T00:00:00+05:30"),
        instant("2026-02-02T00:00:00+05:30"),
    ))

    assert result.meta["source"] == ("rollup" if rolled else "live")
    assert [(row["period"], row["evidence_type"]) for row in result.records] == [
        (date(2026, 2, 1), "issue"), (date(2026, 2, 1), "return"),
    ]
    assert_metrics(result.records[0], created=2, attached=1, size=24, expired=1)
    assert_metrics(result.records[1], created=1, attached=1, size=19, expired=1)
    assert all("makerspace_id" not in row for row in result.records)


@pytest.mark.parametrize("rolled", [False, True], ids=["live", "rolled"])
def test_kolkata_midnight_and_month_fold_use_local_creation_day(report_lab, rolled):
    lab = report_lab
    lab.photo(when=instant("2026-01-31T18:29:59+00:00"), size=2, attached=True)
    boundary = lab.photo(when=instant("2026-01-31T18:30:00+00:00"), size=3, attached=True)
    lab.photo(when=instant("2026-02-01T18:30:00+00:00"), size=5)
    lab.photo(when=CREATED, kind="return", size=7, attached=True)
    assert boundary.created_at.date() == date(2026, 1, 31)
    assert timezone.localdate(boundary.created_at) == date(2026, 2, 1)
    if rolled:
        lab.roll()
    assert lab.sweep()["photos_expired"] == 4

    daily = lab.report()
    assert [(row["period"], row["evidence_type"]) for row in daily.records] == [
        (date(2026, 1, 31), "issue"), (date(2026, 2, 1), "issue"),
        (date(2026, 2, 1), "return"), (date(2026, 2, 2), "issue"),
    ]
    assert [row["object_expired_count"] for row in daily.records] == [1, 1, 1, 1]
    monthly = lab.report(grain="month")
    assert monthly.meta["grain"] == "month"
    assert [(row["period"], row["evidence_type"]) for row in monthly.records] == [
        (date(2026, 1, 1), "issue"), (date(2026, 2, 1), "issue"),
        (date(2026, 2, 1), "return"),
    ]
    assert_metrics(monthly.records[0], created=1, attached=1, size=2, expired=1)
    assert_metrics(monthly.records[1], created=2, attached=1, size=8, expired=2)
    assert_metrics(monthly.records[2], created=1, attached=1, size=7, expired=1)


@pytest.mark.parametrize("rolled", [False, True], ids=["live", "rolled"])
def test_aggregate_preserves_tenant_rows_and_real_module_visibility_gates(report_lab, rolled):
    lab = report_lab
    other = make_space("expiry-aggregate-other")
    excluded = [make_space(f"expiry-excluded-{reason}") for reason in (
        "hidden", "archived", "reports", "evidence",
    )]
    lab.photo(size=11, attached=True)
    lab.photo(kind="return", size=13)
    lab.photo(space=other, size=23)
    for space in excluded:
        lab.photo(space=space, size=997)
    assert lab.sweep()["photos_expired"] == 7
    # No terminal state and no physical bytes: still a live reference, size unknown.
    missing = lab.photo(space=other, size=None)
    for key in (missing.object_key, storage.staging_key(missing.object_key)):
        lab.store.objects.pop(key)
    if rolled:
        for space in [lab.space, other, *excluded]:
            lab.roll(space=space)
    excluded[0].superadmin_access_enabled = False
    excluded[0].save(update_fields=["superadmin_access_enabled"])
    excluded[1].archived_at = timezone.now()
    excluded[1].save(update_fields=["archived_at"])
    for space, module in zip(excluded[2:], ["reports", "evidence_uploads"]):
        space.enabled_modules.remove(module)
        space.save(update_fields=["enabled_modules"])

    result = lab.report(None)

    assert "makerspace_id" in result.field_order
    assert [(row["makerspace_id"], row["evidence_type"]) for row in result.records] == [
        (lab.space.pk, "issue"), (lab.space.pk, "return"), (other.pk, "issue"),
    ]
    assert_metrics(result.records[0], created=1, attached=1, size=11, expired=1)
    assert_metrics(result.records[1], created=1, attached=0, size=13, expired=1)
    assert_metrics(result.records[2], created=2, attached=0, size=23, expired=1)
    assert lab.report(None, limit=1).records == result.records[:1]
