"""Terminal expiry totals shared by evidence reports and rollup snapshots."""

from django.db.models import Count
from django.db.models.functions import TruncDay
from django.utils import timezone

from apps.evidence.retention_models import EvidenceObjectRetentionState


def terminal_expiry_counts(evidence):
    """Aggregate an already tenant/date-scoped EvidencePhoto queryset by local day/type."""
    rows = (
        evidence.filter(object_retention_state__status=EvidenceObjectRetentionState.Status.EXPIRED)
        .order_by()
        .annotate(creation_day=TruncDay("created_at", tzinfo=timezone.get_current_timezone()))
        .values("creation_day", "evidence_type")
        .annotate(expired_count=Count("id"))
    )
    return {
        (timezone.localdate(row["creation_day"]), row["evidence_type"]): row["expired_count"]
        for row in rows
    }
