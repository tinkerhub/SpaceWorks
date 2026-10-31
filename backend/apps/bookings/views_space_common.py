"""Read-only space resolution shared by booking metadata and image routes."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.bookings.models import BookableSpace
from apps.hardware_requests.view_helpers import ERROR_400, ERROR_403, ERROR_404, ERROR_503
from apps.makerspaces.guards import require_module


SCOPED_ERROR_RESPONSES = {403: ERROR_403, 404: ERROR_404}
VALIDATED_ERROR_RESPONSES = {400: ERROR_400, **SCOPED_ERROR_RESPONSES}
IMAGE_ERROR_RESPONSES = {**VALIDATED_ERROR_RESPONSES, 503: ERROR_503}


def manageable_space(actor, pk):
    space = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_BOOKINGS,
            BookableSpace.objects.select_related('makerspace'),
            field='makerspace_id',
        ),
        pk=pk,
    )
    require_module(space.makerspace, 'bookings')
    if not rbac.can(actor, rbac.Action.MANAGE_BOOKINGS, space.makerspace_id):
        raise PermissionDenied()
    return space


def _require_active(space):
    if not space.is_active:
        raise ValidationError(
            {'space': 'Inactive spaces cannot have images changed.'}
        )
