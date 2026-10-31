"""Account and browser-origin boundary for private request-history reads."""

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination

from apps.accounts.claim_sessions import claim_context
from apps.accounts.models import User
from apps.makerspaces.models import Makerspace
from apps.makerspaces.origin_scope import staff_origin_scope_allows


class RequestHistoryPagination(PageNumberPagination):
    page_size = 24


class RequestHistoryErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(read_only=True)


class RequestHistoryModuleErrorSerializer(serializers.Serializer):
    module = serializers.ListField(child=serializers.CharField(), read_only=True)


def require_history_account(request, view, makerspace):
    """Require a real account after canonical tenant lookup, before querying history.

    Presence and community membership are submission policies, not credentials for
    historical reads. Shared anonymous principals and walk-in claims cannot own an
    account history, even if one of those principals was accidentally activated.
    """
    user = request.user
    if (
        not user.is_active
        or user.access_status != User.AccessStatus.ACTIVE
        or user.must_change_password
        or user.is_walk_in
        or user.is_tenant_dump_stub
        or claim_context(user) is not None
        or makerspace.anonymous_requester_id == user.pk
        or Makerspace.objects.filter(anonymous_requester_id=user.pk).exists()
    ):
        raise PermissionDenied("Request history requires an active personal account.")
    if not staff_origin_scope_allows(request, view):
        raise PermissionDenied("Request history is outside this site's makerspace.")
