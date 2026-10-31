from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.boxes.models import Box, QrCode
from apps.hardware_requests.self_checkout_workflow import qr_has_active_loan
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.gate_runtime import boundary_tenant_write


@transaction.atomic
def box_write_makerspace(actor, makerspace_id, *, native=False, creation=False):
    """Serialize Box writers; the caller's outer transaction retains both locks.

    Source admission precedes Maker, including for direct service/form callers.
    Native edit/delete deliberately have no creation-only module requirement.
    """
    with boundary_tenant_write(makerspace_id):
        makerspace = get_object_or_404(Makerspace.objects.select_for_update(no_key=True), pk=makerspace_id)
        if creation:
            require_module(makerspace, "qr_management")
        current_actor = User.objects.filter(pk=getattr(actor, "pk", None)).first()
        if (
            current_actor is None
            or not current_actor.is_active
            or current_actor.access_status != User.AccessStatus.ACTIVE
        ):
            raise PermissionDenied()
        if native:
            if not current_actor.is_superuser or current_actor.must_change_password:
                raise PermissionDenied()
            # Native admin never gets the API's hidden-space membership exception.
            if not makerspace.superadmin_access_enabled:
                raise PermissionDenied()
        elif not rbac.can(current_actor, rbac.Action.MANAGE_QR, makerspace.id):
            raise PermissionDenied()
        return makerspace


def create_box_with_qr(actor, box, *, native=False):
    """Save the actual new Box, its usable QR, and its audit as one mutation."""
    if not isinstance(box, Box) or not box._state.adding:
        raise ValueError("Box creation requires a new Box instance.")
    # The boundary surrounds atomic's exit too: no source acquisition under rows.
    with boundary_tenant_write(box.makerspace_id), transaction.atomic():
        box.makerspace = box_write_makerspace(
            actor, box.makerspace_id, native=native, creation=True,
        )
        if box.parent_id is not None:
            box.parent = get_object_or_404(Box, pk=box.parent_id, makerspace_id=box.makerspace_id)
        if Box.objects.filter(makerspace=box.makerspace, label=box.label).exists():
            # Preserve the existing API field error; model constraints use __all__.
            raise ValidationError({"label": ["A container with this label already exists in this makerspace."]})
        try:
            box.full_clean()
        except ModelValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        try:
            with transaction.atomic():
                box.save(force_insert=True)
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)
            if constraint != "uniq_box_label_per_makerspace":
                raise
            raise ValidationError({"label": ["A container with this label already exists in this makerspace."]}) from exc
        QrCode.objects.create(
            makerspace=box.makerspace,
            payload=box.code,
            target_type=QrCode.TargetType.BOX,
            target_id=box.pk,
            created_by=actor,
        )
        audit.record(actor, "qr.box_created", makerspace=box.makerspace, target=box)
        return box


def revoke_qr_code(actor, qr):
    from apps.boxes.access import qr_for_action
    from apps.boxes.qr_admission import current_qr_actor, fresh_qr, qr_identity, qr_write

    actor = current_qr_actor(actor)
    initial = qr_for_action(actor, rbac.Action.MANAGE_QR, pk=qr.pk, makerspace_id=qr.makerspace_id)
    if qr_identity(initial) != qr_identity(qr):
        from apps.boxes.exceptions import Conflict

        raise Conflict("QR target changed before admission; retry the operation.")
    require_module(initial.makerspace, "qr_management")
    with qr_write([initial.makerspace_id]):
        actor = current_qr_actor(actor)
        qr = fresh_qr(actor, initial, rbac.Action.MANAGE_QR)
        require_module(qr.makerspace, "qr_management")
        if qr.status == QrCode.Status.REVOKED:
            raise ValidationError("QR code is already revoked.")
        if qr_has_active_loan(qr.makerspace, qr):
            raise ValidationError("Cannot revoke a QR code with an outstanding loan.")

        qr.status = QrCode.Status.REVOKED
        qr.revoked_at = timezone.now()
        qr.save(update_fields=["status", "revoked_at", "updated_at"])
        audit.record(actor, "qr.revoked", makerspace=qr.makerspace, target=qr)
        return qr
