from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from apps.evidence.models import EvidencePhoto
from apps.evidence.report_expiry import terminal_expiry_counts
from apps.operations.models import ReportMetricRollup, ReportRollupCursor
from apps.operations.report_rollups import METRICS, REPORT_KEY, SOURCE_MODULE, _attached_ids
from apps.operations.report_types import ReportResult
from apps.operations.reports_common import limited, report_spaces


FIELDS = (
    "period", "evidence_type", "created_count", "attached_count",
    "unattached_count", "object_live_count", "object_expired_count",
    "metadata_retained_count", "bytes", "attachment_rate_percent",
)


def build_evidence_compliance(makerspace_id, *, limit=None, date_range=None, grain="day"):
    aggregate = makerspace_id is None
    records = []
    sources = set()
    watermarks = []
    for space in report_spaces(makerspace_id, SOURCE_MODULE):
        cursor = ReportRollupCursor.objects.filter(makerspace=space, source_module=SOURCE_MODULE).first()
        if cursor and cursor.rolled_through:
            watermarks.append(cursor.rolled_through)
        buckets = _rolled_buckets(space.id, date_range, cursor)
        if buckets:
            sources.add("rollup")
        live_start = cursor.rolled_through if cursor and cursor.rolled_through else None
        live = _live_buckets(space.id, date_range, live_start)
        if live:
            sources.add("live")
        _merge(records, space.id, aggregate, buckets, live, grain=grain)
    source = "hybrid" if len(sources) > 1 else next(iter(sources), "live")
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    return ReportResult(fields, limited(records, limit), {
        "source": source, "grain": grain,
        "rollup_through": min(watermarks) if watermarks else None,
        "object_count_basis": (
            "Historical created_count minus currently retained metadata with terminal expired state; "
            "expiring is not expired. Upload and storage presence are unknown: no object-store probe. "
            "Metadata deletion also removes expiry state, so expired counts may fall and derived live "
            "counts rise, including after rerolling; prior expiry snapshots are not preserved on read. "
            "metadata_retained_count is a live count or stored rollup snapshot. "
            "bytes sums recorded sizes, not current storage or quota usage."
        ),
    })


def _rolled_buckets(space_id, date_range, cursor):
    if cursor is None or cursor.rolled_through is None:
        return {}
    qs = ReportMetricRollup.objects.filter(
        makerspace_id=space_id, report_key=REPORT_KEY,
        bucket_start__lt=cursor.rolled_through,
    ).order_by("bucket_start", "dimension_key", "metric_key", "-revision")
    if date_range:
        start, end = date_range
        if start:
            qs = qs.filter(bucket_start__gte=start)
        if end:
            qs = qs.filter(bucket_start__lt=end)
    latest = {}
    for row in qs:
        key = (row.bucket_start, row.dimension_key, row.metric_key)
        latest.setdefault(key, row)
    buckets = defaultdict(dict)
    for (bucket, _dimension, metric), row in latest.items():
        evidence_type = row.dimensions["evidence_type"]
        buckets[(timezone.localdate(bucket), evidence_type)][metric] = row.value
    if buckets:
        starts = [bucket for bucket, _dimension, _metric in latest]
        expiry_start = min(starts)
        expiry_end = min(cursor.rolled_through, timezone.localtime(max(starts)) + timedelta(days=1))
        if date_range:
            start, end = date_range
            if start:
                expiry_start = max(expiry_start, start)
            if end:
                expiry_end = min(expiry_end, end)
        expired = terminal_expiry_counts(EvidencePhoto.objects.filter(
            makerspace_id=space_id, created_at__gte=expiry_start, created_at__lt=expiry_end,
        ))
        for key, values in buckets.items():
            # Derive from historical creations, never an already reduced live snapshot.
            values["object_expired_count"] = expired.get(key, 0)
            values["object_live_count"] = values.get("created_count", 0) - values["object_expired_count"]
    return buckets


def _live_buckets(space_id, date_range, live_start):
    qs = EvidencePhoto.objects.filter(makerspace_id=space_id)
    if live_start:
        qs = qs.filter(created_at__gte=live_start)
    if date_range:
        start, end = date_range
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lt=end)
    rows = defaultdict(lambda: defaultdict(int))
    for evidence in qs.only("id", "evidence_type", "created_at", "size_bytes").iterator(chunk_size=200):
        key = (timezone.localdate(evidence.created_at), evidence.evidence_type)
        rows[key]["created_count"] += 1
        rows[key]["metadata_retained_count"] += 1
        rows[key]["bytes"] += evidence.size_bytes or 0
    ids = qs.values_list("id", flat=True)
    attached = _attached_ids(space_id, ids)
    for evidence_type, attached_ids in attached.items():
        dates = dict(EvidencePhoto.objects.filter(id__in=attached_ids).values_list("id", "created_at"))
        for created_at in dates.values():
            rows[(timezone.localdate(created_at), evidence_type)]["attached_count"] += 1
    expired = terminal_expiry_counts(qs)
    for key, values in rows.items():
        values["unattached_count"] = values["created_count"] - values["attached_count"]
        values["object_expired_count"] = expired.get(key, 0)
        values["object_live_count"] = values["created_count"] - values["object_expired_count"]
    return rows


def _merge(records, space_id, aggregate, *sources, grain):
    merged = defaultdict(lambda: defaultdict(int))
    for source in sources:
        for (period, evidence_type), metrics in source.items():
            period = period.replace(day=1) if grain == "month" else period
            target = merged[(period, evidence_type)]
            for metric in METRICS:
                target[metric] += metrics.get(metric, 0)
    for (period, evidence_type), metrics in sorted(merged.items()):
        created = metrics["created_count"]
        row = {
            "period": period, "evidence_type": evidence_type, **metrics,
            "attachment_rate_percent": round(float(metrics["attached_count"] / created * 100), 2) if created else None,
        }
        if aggregate:
            row["makerspace_id"] = space_id
        records.append(row)
