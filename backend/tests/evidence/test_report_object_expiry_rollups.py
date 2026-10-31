"""Expiry overlays append-only snapshots, including beyond the refresh window."""

from datetime import date, timedelta

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.evidence.models import EvidenceObjectRetentionState, EvidencePhoto
from apps.operations.models import ReportMetricRollup, ReportRollupCursor
from tests.evidence.report_object_expiry_helpers import (
    AS_OF, CREATED, assert_metrics, attachment_snapshot, historical, instant,
    metadata_snapshot, report_audit_snapshot, report_lab, rollup_snapshot,
)


pytestmark = pytest.mark.django_db


def test_old_rollup_reflects_sweep_without_rewriting_rows_or_report_audit(report_lab):
    lab = report_lab
    lab.photo(size=11, attached=True)
    lab.photo(size=23)
    lab.photo(kind="return", size=31, attached=True)
    through = instant("2026-03-15T00:00:00+05:30")
    lab.roll(through=through)
    before = lab.report()
    rows = rollup_snapshot(lab.space)
    audits = report_audit_snapshot(lab.space)
    metadata = metadata_snapshot(lab.space)
    attachments = attachment_snapshot(lab.space)
    cursor = ReportRollupCursor.objects.values().get(makerspace=lab.space)
    assert through - CREATED > timedelta(days=7)
    assert all(row["revision"] == 1 for row in rows)
    assert_metrics(before.records[0], created=2, attached=1, size=34, expired=0)
    assert_metrics(before.records[1], created=1, attached=1, size=31, expired=0)

    summary = lab.sweep()

    assert summary["photos_expired"] == 3 and summary["photos_failed"] == 0
    assert report_audit_snapshot(lab.space) == audits
    all_audits = list(AuditLog.objects.order_by("pk").values())
    after = lab.report()
    assert lab.report().records == after.records
    assert_metrics(after.records[0], created=2, attached=1, size=34, expired=2)
    assert_metrics(after.records[1], created=1, attached=1, size=31, expired=1)
    assert after.meta["source"] == "rollup"
    assert after.meta["rollup_through"] == through
    assert historical(after.records) == historical(before.records)
    assert rollup_snapshot(lab.space) == rows
    assert list(AuditLog.objects.order_by("pk").values()) == all_audits
    assert ReportRollupCursor.objects.values().get(makerspace=lab.space) == cursor
    assert metadata_snapshot(lab.space) == metadata
    assert attachment_snapshot(lab.space) == attachments


def test_reroll_appends_only_changed_metrics_and_never_subtracts_twice(report_lab):
    lab = report_lab
    lab.photo(size=11, attached=True)
    lab.photo(when=CREATED + timedelta(hours=2), size=13)
    lab.photo(kind="return", size=19, attached=True)
    lab.roll()
    old_rows = rollup_snapshot(lab.space)
    old_audits = report_audit_snapshot(lab.space)
    metadata = metadata_snapshot(lab.space)
    attachments = attachment_snapshot(lab.space)
    historical_before = historical(lab.report().records)
    assert lab.sweep(now=CREATED + timedelta(days=30, hours=1))["photos_expired"] == 2
    overlaid = lab.report()

    changed = lab.roll(start_at=CREATED)

    assert changed == 4  # Live + expired for each of issue and return; no other fact changed.
    new_rows = list(ReportMetricRollup.objects.filter(
        makerspace=lab.space, revision=2,
    ).values("metric_key", "dimensions", "value"))
    assert {(row["dimensions"]["evidence_type"], row["metric_key"]): row["value"]
            for row in new_rows} == {
        ("issue", "object_expired_count"): 1, ("issue", "object_live_count"): 1,
        ("return", "object_expired_count"): 1, ("return", "object_live_count"): 0,
    }
    assert [row for row in rollup_snapshot(lab.space) if row["revision"] == 1] == old_rows
    old_audit_ids = {row["id"] for row in old_audits}
    assert [row for row in report_audit_snapshot(lab.space)
            if row["id"] in old_audit_ids] == old_audits
    assert_metrics(lab.report().records[0], created=2, attached=1, size=24, expired=1)
    assert_metrics(lab.report().records[1], created=1, attached=1, size=19, expired=1)
    assert lab.report().records == overlaid.records
    assert historical(lab.report().records) == historical_before
    assert metadata_snapshot(lab.space) == metadata
    assert attachment_snapshot(lab.space) == attachments
    revision_audits = AuditLog.objects.filter(action="report.rollup_revision_appended").count()
    rows = rollup_snapshot(lab.space)
    assert lab.roll(start_at=CREATED) == 0
    assert rollup_snapshot(lab.space) == rows
    assert AuditLog.objects.filter(action="report.rollup_revision_appended").count() == revision_audits
    assert lab.report().records == overlaid.records


@pytest.mark.django_db(transaction=True)
def test_maintenance_delete_after_expiry_and_reroll_preserves_historical_fallback(report_lab):
    lab = report_lab
    expired = lab.photo(size=17)
    retained = lab.photo(when=CREATED + timedelta(hours=2), size=23, attached=True)
    lab.roll()
    before = lab.report()
    metadata = metadata_snapshot(lab.space)
    attachments = attachment_snapshot(lab.space)
    assert lab.sweep(now=CREATED + timedelta(days=30, hours=1))["photos_expired"] == 1
    assert lab.roll(start_at=CREATED) == 2
    assert_metrics(lab.report().records[0], created=2, attached=1, size=40, expired=1)
    assert ReportMetricRollup.objects.get(
        makerspace=lab.space, metric_key="object_expired_count", revision=2,
    ).value == 1
    rows = rollup_snapshot(lab.space)
    audits = list(AuditLog.objects.order_by("pk").values())
    assert EvidenceObjectRetentionState.objects.get(evidence=expired).status == "expired"

    # Same sanctioned maintenance hatch as test_report_coverage_rollups.py.
    # Delete an unattached row only; inbound PROTECT links remain fully enforced.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        EvidencePhoto.objects.filter(pk=expired.pk).delete()

    assert not EvidenceObjectRetentionState.objects.filter(evidence_id=expired.pk).exists()
    assert metadata_snapshot(lab.space) == [row for row in metadata if row["id"] == retained.pk]
    assert attachment_snapshot(lab.space) == attachments
    after = lab.report()
    assert_metrics(after.records[0], created=2, attached=1, size=40, expired=0)
    assert historical(after.records) == historical(before.records)
    assert rollup_snapshot(lab.space) == rows
    assert list(AuditLog.objects.order_by("pk").values()) == audits
    basis = after.meta["object_count_basis"].lower()
    assert "metadata deletion" in basis and "counts rise" in basis
    assert "prior expiry snapshots are not preserved" in basis
    # The rise to two live references is arithmetic; deleted bytes never reappear.
    assert expired.object_key not in lab.store.objects
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.allow_immutable_delete', true)")
        assert cursor.fetchone()[0] != "on"


def test_hybrid_cursor_boundary_combines_rolled_expiry_with_unrolled_rows_once(report_lab):
    lab = report_lab
    through = instant("2026-02-02T00:00:00+05:30")
    lab.photo(size=11, attached=True)
    lab.photo(when=through, kind="return", size=13, attached=True)
    lab.photo(when=AS_OF - timedelta(days=1), size=17)
    lab.roll(through=through)
    before = lab.report()
    assert before.meta["source"] == "hybrid"
    assert lab.sweep()["photos_expired"] == 2

    after = lab.report()

    assert after.meta["source"] == "hybrid"
    assert after.meta["rollup_through"] == through
    assert [(row["period"], row["evidence_type"]) for row in after.records] == [
        (date(2026, 2, 1), "issue"), (date(2026, 2, 2), "return"),
        (timezone.localdate(AS_OF - timedelta(days=1)), "issue"),
    ]
    assert_metrics(after.records[0], created=1, attached=1, size=11, expired=1)
    assert_metrics(after.records[1], created=1, attached=1, size=13, expired=1)
    assert_metrics(after.records[2], created=1, attached=0, size=17, expired=0)
    assert historical(after.records) == historical(before.records)
    assert lab.report(date_range=(through, None)).records == after.records[1:]
    assert lab.report(date_range=(None, through)).records == after.records[:1]
