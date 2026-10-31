"""Exact service-owned retry route; no generic admin mutation bypass."""

from functools import wraps

from django.db import transaction
from django.urls import path

from apps.makerspaces.admin_purge_receipts import retry_cleanup_view


def receipt_urls(model_admin):
    @wraps(retry_cleanup_view)
    def bound_view(request, receipt_id):
        return retry_cleanup_view(request, receipt_id, model_admin)

    protected = transaction.non_atomic_requests(model_admin.admin_site.admin_view(bound_view))
    return [path(
        "<uuid:receipt_id>/retry-cleanup/", protected,
        name="makerspaces_purgereceipt_retry_cleanup",
    )]
