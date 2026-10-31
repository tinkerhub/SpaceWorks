"""Literal admin route, discoverable by the source-gate URL scanner."""

from functools import wraps

from django.db import transaction
from django.urls import path

from apps.makerspaces.admin_purge import confirmed_purge_view


def purge_urls(model_admin):
    @wraps(confirmed_purge_view)
    def bound_view(request):
        return confirmed_purge_view(request, model_admin)

    protected = transaction.non_atomic_requests(
        model_admin.admin_site.admin_view(bound_view)
    )
    return [path(
        "purge-confirmed/", protected,
        name="makerspaces_makerspace_purge_confirmed",
    )]
