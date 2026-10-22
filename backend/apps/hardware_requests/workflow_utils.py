from apps.hardware_requests.models import HardwareRequest


def constraint_name(exc):
    diag = getattr(getattr(exc, "__cause__", None), "diag", None)
    return getattr(diag, "constraint_name", "") or ""


def locked_request(request):
    # Nullable FKs must not be select_related under SELECT FOR UPDATE in Postgres.
    # of=("self",) locks only the request row: without it Postgres also takes FOR UPDATE
    # on the joined makerspace and requester rows, which blocks every concurrent insert
    # that references them (FK KEY SHARE) for the whole workflow transaction.
    return (
        HardwareRequest.objects.select_for_update(of=("self",))
        .select_related("makerspace", "requester")
        .get(pk=request.pk)
    )
