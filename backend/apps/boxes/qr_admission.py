"""QR-local source admission and fresh policy checks; never acquires Maker rows."""

from contextlib import ExitStack, contextmanager

from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.boxes.access import locked_qr_for_action
from apps.boxes.exceptions import Conflict
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.gate_runtime import boundary_tenant_write


@contextmanager
def qr_sources(makerspace_ids):
    with ExitStack() as stack:
        for pk in sorted({int(pk) for pk in makerspace_ids}):
            stack.enter_context(boundary_tenant_write(pk))
        yield


@contextmanager
def qr_write(makerspace_ids):
    # Outside atomic this retains dedicated boundaries through commit; inside an
    # outer atomic the existing helper retains SQL locks until that outer commit.
    with qr_sources(makerspace_ids), transaction.atomic():
        yield


def current_qr_actor(actor, *, native=False, makerspace_ids=()):
    actor = User.objects.filter(pk=getattr(actor, "pk", None)).first()
    if actor is None or not actor.is_active or actor.access_status != User.AccessStatus.ACTIVE:
        raise PermissionDenied()
    if native:
        if not actor.is_superuser or actor.must_change_password:
            raise PermissionDenied()
        ids = {int(pk) for pk in makerspace_ids}
        visible = set(Makerspace.objects.filter(
            pk__in=ids, superadmin_access_enabled=True,
        ).values_list("pk", flat=True))
        if visible != ids or any(not rbac.can(actor, rbac.Action.MANAGE_QR, pk) for pk in ids):
            raise PermissionDenied()
    return actor


def qr_identity(qr):
    return (qr.makerspace_id, qr.target_type, qr.target_id)


def fresh_qr(actor, initial, action, *, active=False):
    filters = {"pk": initial.pk, "makerspace_id": initial.makerspace_id}
    if active:
        filters["status"] = initial.Status.ACTIVE
    qr = locked_qr_for_action(actor, action, **filters)
    actor = current_qr_actor(actor)
    if not rbac.can(actor, action, qr.makerspace_id):
        raise PermissionDenied()
    if qr_identity(qr) != qr_identity(initial):
        raise Conflict("QR target changed while waiting; retry the operation.")
    return qr


@contextmanager
def admitted_qr(actor, initial, action, module):
    from apps.boxes.access import qr_for_action
    from apps.makerspaces.guards import require_module

    actor = current_qr_actor(actor)
    snapshot = initial
    initial = qr_for_action(actor, action, pk=initial.pk, makerspace_id=initial.makerspace_id)
    if qr_identity(initial) != qr_identity(snapshot):
        raise Conflict("QR target changed before admission; retry the operation.")
    require_module(initial.makerspace, module)
    with qr_write([initial.makerspace_id]):
        qr = fresh_qr(actor, initial, action, active=True)
        actor = current_qr_actor(actor)
        require_module(qr.makerspace, module)
        yield actor, qr


def create_tool_qr(actor, makerspace_id, target, target_type):
    from django.shortcuts import get_object_or_404
    from rest_framework.exceptions import ValidationError

    from apps.audit import services as audit
    from apps.boxes.access import makerspace_for_action
    from apps.boxes.models import QrCode
    from apps.inventory.models import TrackingMode
    from apps.makerspaces.guards import require_module

    actor = current_qr_actor(actor)
    makerspace = makerspace_for_action(actor, rbac.Action.MANAGE_QR, makerspace_id)
    require_module(makerspace, "qr_management")
    model = type(target)
    target = get_object_or_404(model, pk=target.pk, makerspace_id=makerspace_id)
    with qr_write([makerspace_id]):
        # Checkout and rebind both lock a reusable QR before its target.
        qr = QrCode.objects.select_for_update().filter(
            makerspace_id=makerspace_id, target_type=target_type,
            target_id=target.pk, status=QrCode.Status.ACTIVE,
        ).first()
        target = get_object_or_404(
            model.objects.select_for_update(), pk=target.pk, makerspace_id=makerspace_id,
        )
        actor = current_qr_actor(actor)
        makerspace = makerspace_for_action(actor, rbac.Action.MANAGE_QR, makerspace_id)
        require_module(makerspace, "qr_management")
        if target_type == QrCode.TargetType.PRODUCT and target.tracking_mode == TrackingMode.INDIVIDUAL:
            raise ValidationError("Individual-tracked inventory requires unit QR codes.")
        created = False
        if qr is None:
            qr, created = QrCode.objects.get_or_create(
                makerspace=makerspace, target_type=target_type, target_id=target.pk,
                status=QrCode.Status.ACTIVE, defaults={"created_by": actor},
            )
        audit.record(
            actor, "qr.tool_created" if created else "qr.tool_reused",
            makerspace=makerspace, target=target, meta={"qr_id": qr.id},
        )
        return qr


def require_qr_request_scope(request, makerspace_ids):
    """Bind the actual unlocked owner(s), rather than a body hint, to the site."""
    from apps.makerspaces.origin_scope import (
        AMBIGUOUS_STAFF_ORIGIN_SCOPE, NO_STAFF_ORIGIN_SCOPE, staff_origin_scope,
    )

    scope = staff_origin_scope(request)
    selected = getattr(request, "selected_makerspace_id", None)
    ids = {int(pk) for pk in makerspace_ids}
    if (scope is AMBIGUOUS_STAFF_ORIGIN_SCOPE
            or (scope is not NO_STAFF_ORIGIN_SCOPE and ids != {scope})
            or (selected is not None and ids != {selected})):
        raise PermissionDenied()
