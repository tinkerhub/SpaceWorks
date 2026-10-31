from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.filters import BaseFilterBackend
from django.db.models import Q
from django.conf import settings

from apps.accounts import rbac
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.permissions import (
    CanReviewRequest, CanViewAcceptedRequestQueue, CanViewHandoverQueue,
)
from apps.hardware_requests.serializers import AdminRequestSerializer
from apps.hardware_requests.view_helpers import (
    ADMIN_LIST_ERROR_RESPONSES,
    request_queryset,
    handover_surface_module,
)
from apps.makerspaces.models import Makerspace
from apps.makerspaces.guards import require_module

# Staff search the queues by who borrowed / what for. Scoped to the queue's own
# makerspace filter already, so this only narrows within the tenant.
REQUEST_SEARCH_FIELDS = ["requested_for"]


class ScopedPiiSearchFilter(BaseFilterBackend):
    def get_schema_operation_parameters(self, view):
        # Keep the `search` query parameter documented in OpenAPI even though this
        # is a custom backend (blind-index/plaintext resolution happens internally).
        return [{
            "name": "search",
            "required": False,
            "in": "query",
            "description": "A search term (requested-for, requester name/email).",
            "schema": {"type": "string"},
        }]

    def filter_queryset(self, request, queryset, view):
        term = request.query_params.get("search", "").strip()
        if not term:
            return queryset
        if not settings.PII_ENCRYPTION_ENABLED:
            return queryset.filter(Q(requested_for__icontains=term) | Q(requester_name__icontains=term) | Q(requester_contact_email__icontains=term))
        from rest_framework.exceptions import ValidationError

        from apps.encryption.search import indexed_candidates, legacy_plaintext_candidates, verified_ids
        makerspace_id = view.kwargs["makerspace_id"]
        ids = set()
        for field_name, exact in (("requester_name", False), ("requester_contact_email", True)):
            try:
                candidates = indexed_candidates(makerspace_id=makerspace_id, model_label="hardware_requests.HardwareRequest", field_name=field_name, term=term, exact=exact)
            except ValidationError:  # e.g. name term shorter than a trigram
                candidates = []
            ids.update(verified_ids(queryset.filter(pk__in=candidates), field_name=field_name, term=term, exact=exact))
            # During the dual-read rollout, pre-backfill rows have no index yet.
            if settings.PII_ENCRYPTION_DUAL_READ:
                ids.update(legacy_plaintext_candidates(queryset, field_name=field_name, term=term, exact=exact))
        return queryset.filter(Q(requested_for__icontains=term) | Q(pk__in=ids))


class PendingRequestsView(generics.ListAPIView):
    permission_classes = [CanReviewRequest]
    serializer_class = AdminRequestSerializer
    filter_backends = [ScopedPiiSearchFilter]
    search_fields = REQUEST_SEARCH_FIELDS

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "request_workflow")
        _require_any_action(
            self.request.user, makerspace_id, rbac.Action.ACCEPT_REQUEST, rbac.Action.REJECT_REQUEST,
        )
        return (
            request_queryset().select_related("closed_by")
            .filter(
                makerspace_id=makerspace_id,
                status=HardwareRequest.Status.PENDING_APPROVAL,
            )
            .order_by("-created_at")
        )

    @extend_schema(
        tags=["Admin requests"],
        summary="List pending borrow requests",
        responses={200: AdminRequestSerializer(many=True), **ADMIN_LIST_ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class AcceptedRequestsView(generics.ListAPIView):
    permission_classes = [CanViewAcceptedRequestQueue]
    serializer_class = AdminRequestSerializer
    filter_backends = [ScopedPiiSearchFilter]
    search_fields = REQUEST_SEARCH_FIELDS

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, handover_surface_module(self.request))
        _require_any_action(
            self.request.user, makerspace_id, rbac.Action.ISSUE_REQUEST, rbac.Action.REJECT_REQUEST,
        )
        return (
            request_queryset().select_related("closed_by")
            .filter(
                makerspace_id=makerspace_id,
                status=HardwareRequest.Status.ACCEPTED,
            )
            .order_by("-created_at")
        )

    @extend_schema(
        tags=["Admin requests"],
        summary="List accepted requests awaiting issue",
        responses={200: AdminRequestSerializer(many=True), **ADMIN_LIST_ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ActiveLoansView(generics.ListAPIView):
    permission_classes = [CanViewHandoverQueue]
    serializer_class = AdminRequestSerializer
    filter_backends = [ScopedPiiSearchFilter]
    search_fields = REQUEST_SEARCH_FIELDS

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, handover_surface_module(self.request))
        _require_action(self.request.user, rbac.Action.ISSUE_REQUEST, makerspace_id)
        return (
            request_queryset().select_related("closed_by")
            .filter(
                makerspace_id=makerspace_id,
                status__in=[
                    HardwareRequest.Status.ISSUED,
                    HardwareRequest.Status.PARTIALLY_RETURNED,
                ],
                # Self-checkout and direct handouts are returned through their
                # PublicToolLoan, never the reviewed-request return this queue drives.
                public_tool_loan__isnull=True,
            )
            .order_by("-issued_at", "-created_at")
        )

    @extend_schema(
        tags=["Admin requests"],
        summary="List active loans awaiting return",
        responses={200: AdminRequestSerializer(many=True), **ADMIN_LIST_ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class RequestHistoryView(generics.ListAPIView):
    # Review-only staff see rejected/cancelled decisions, never returned-loan PII.
    permission_classes = [CanViewAcceptedRequestQueue]
    serializer_class = AdminRequestSerializer
    filter_backends = [ScopedPiiSearchFilter]
    search_fields = REQUEST_SEARCH_FIELDS

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, handover_surface_module(self.request))
        _require_any_action(
            self.request.user, makerspace_id, rbac.Action.ISSUE_REQUEST, rbac.Action.REJECT_REQUEST,
        )
        statuses = [HardwareRequest.Status.REJECTED, HardwareRequest.Status.CANCELLED]
        if rbac.can(self.request.user, rbac.Action.ISSUE_REQUEST, makerspace_id):
            statuses.extend([
                HardwareRequest.Status.RETURNED, HardwareRequest.Status.CLOSED_WITH_ISSUE,
            ])
        return (
            request_queryset().select_related("closed_by")
            .filter(
                makerspace_id=makerspace_id,
                status__in=statuses,
            )
            .order_by("-updated_at", "-created_at")
        )

    @extend_schema(
        tags=["Admin requests"],
        summary="List terminal requests allowed by issue or review authority",
        responses={200: AdminRequestSerializer(many=True), **ADMIN_LIST_ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


def _require_action(user, action, makerspace_id):
    scoped = rbac.scope_by_action(user, action, Makerspace.objects.all(), field="id")
    get_object_or_404(scoped, pk=makerspace_id)


def _require_any_action(user, makerspace_id, *actions):
    scope = rbac.makerspaces_for_actions(user, *actions)
    scoped = Makerspace.objects.all()
    if scope is not rbac.ALL:
        scoped = scoped.filter(pk__in=scope)
    get_object_or_404(scoped, pk=makerspace_id)
