"""Thin re-export barrel over the request serializers.

The classes moved into `serializers_public` (the public submit/status surface) and
`serializers_admin` (the staff review/issue/return surface) when this file crossed
the repo's 300-line hard ceiling. Fourteen modules import from `apps.hardware_requests.serializers`,
so the names are re-exported explicitly here — never `import *`, which would make the
public surface of this module depend on import order.
"""

from apps.hardware_requests.serializers_admin import (
    AcceptQuantitySerializer,
    AcceptRequestSerializer,
    AdminRequestActorSerializer,
    AdminRequestItemSerializer,
    AdminRequestSerializer,
    AssignBoxSerializer,
    IssueRejectSerializer,
    IssueRequestSerializer,
    IssuedAssetSerializer,
    RejectRequestSerializer,
    ReturnAssetResolutionSerializer,
    ReturnDueSerializer,
    ReturnItemResolutionSerializer,
    ReturnRequestSerializer,
)
from apps.hardware_requests.serializers_public import (
    PublicRequestItemStatusSerializer,
    PublicRequestStatusSerializer,
    RequestItemInputSerializer,
    RequestSubmitResponseSerializer,
    RequestSubmitSerializer,
)

__all__ = [
    "AcceptQuantitySerializer",
    "AcceptRequestSerializer",
    "AdminRequestActorSerializer",
    "AdminRequestItemSerializer",
    "AdminRequestSerializer",
    "AssignBoxSerializer",
    "IssueRejectSerializer",
    "IssueRequestSerializer",
    "IssuedAssetSerializer",
    "PublicRequestItemStatusSerializer",
    "PublicRequestStatusSerializer",
    "RejectRequestSerializer",
    "RequestItemInputSerializer",
    "RequestSubmitResponseSerializer",
    "RequestSubmitSerializer",
    "ReturnAssetResolutionSerializer",
    "ReturnDueSerializer",
    "ReturnItemResolutionSerializer",
    "ReturnRequestSerializer",
]
