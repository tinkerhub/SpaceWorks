"""Recorded machine hours shared by staff, public projections and operations."""

from decimal import Decimal

from django.db.models import (
    DecimalField, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum, Value,
)
from django.db.models.functions import Cast, Coalesce, Round

from apps.machines.models import Machine, MachineServiceRequest, MachineUsageEntry


TERMINAL_STATUSES = (
    MachineServiceRequest.Status.COMPLETED,
    MachineServiceRequest.Status.COLLECTED,
    MachineServiceRequest.Status.FAILED,
)


def _period_q(field, date_range):
    query = Q()
    if date_range:
        start, end = date_range
        if start is not None:
            query &= Q(**{f"{field}__gte": start})
        if end is not None:
            query &= Q(**{f"{field}__lt": end})
    return query


def annotate_machine_usage(queryset, *, date_range=None):
    """Annotate an already-scoped Machine queryset with rounded ``usage_total``.

    Independent correlated sums prevent ledger/request join multiplication.
    A linked terminal run supersedes its ledger hours regardless of the report
    window; only the retained sources are then filtered by their own timestamps.
    """
    numeric = DecimalField(max_digits=20, decimal_places=2)
    zero = Value(Decimal("0.00"), output_field=numeric)
    manual = (
        MachineUsageEntry.objects.filter(machine_id=OuterRef("pk"))
        .exclude(
            service_request__status__in=TERMINAL_STATUSES,
            service_request__actual_minutes__gt=0,
            service_request__assigned_machine_id=F("machine_id"),
            service_request__makerspace_id=OuterRef("makerspace_id"),
        )
        .filter(_period_q("created_at", date_range))
        .order_by()
        .values("machine_id")
        .annotate(total=Sum("hours"))
    )
    completed = Q(status__in=(
        MachineServiceRequest.Status.COMPLETED,
        MachineServiceRequest.Status.COLLECTED,
    )) & _period_q("completed_at", date_range)
    failed = Q(status=MachineServiceRequest.Status.FAILED) & _period_q(
        "failed_at", date_range
    )
    service = (
        MachineServiceRequest.objects.filter(
            assigned_machine_id=OuterRef("pk"),
            makerspace_id=OuterRef("makerspace_id"),
            actual_minutes__gt=0,
        )
        .filter(completed | failed)
        .order_by()
        .values("assigned_machine_id")
        .annotate(total=Sum("actual_minutes"))
    )
    manual_hours = Coalesce(Subquery(manual.values("total")), zero)
    # Cast before division so integer minutes use numeric, rather than integer,
    # division. Sum minutes first and round only the combined per-machine hours.
    minutes = Coalesce(Cast(Subquery(service.values("total")), numeric), zero)
    total = ExpressionWrapper(
        manual_hours + minutes / Value(Decimal("60")), output_field=numeric
    )
    return queryset.annotate(usage_total=Round(total, 2))


def machine_usage_total(machine):
    """Detail fallback uses exactly the same SQL expression as list/report rows."""
    return annotate_machine_usage(
        Machine.objects.filter(pk=machine.pk, makerspace_id=machine.makerspace_id)
    ).values_list("usage_total", flat=True).get()
