from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.boxes.models import QrCode
from apps.boxes.qr_admission import current_qr_actor, qr_write
from apps.boxes.targets import qr_target
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked
from apps.operations.models import QrPrintBatch, QrPrintBatchItem


def _label_with_suffix(name, suffix):
    # Fit the descriptive name while keeping the complete identifier/number suffix.
    return f"{name[:255 - len(suffix)]}{suffix}"


def _target_label(qr):
    target = qr_target(qr)
    if qr.target_type == QrCode.TargetType.BOX:
        return target.label
    if qr.target_type == QrCode.TargetType.ASSET:
        return _label_with_suffix(target.product.name, f" - {target.asset_tag}")
    return target.name


@transaction.atomic
def add_qr_to_batch(actor, batch, qr, label_text="", sort_order=None):
    if qr.makerspace_id != batch.makerspace_id:
        raise ValidationError("QR code belongs to a different makerspace.")
    if len(label_text) > 255:
        raise ValidationError({"label_text": "Ensure this field has no more than 255 characters."})
    qr = get_object_or_404(
        QrCode.objects.select_for_update(), pk=qr.pk, makerspace_id=batch.makerspace_id
    )
    actor = current_qr_actor(actor)
    if not rbac.can(actor, rbac.Action.MANAGE_QR, batch.makerspace_id):
        raise PermissionDenied()
    target_label = _target_label(qr)
    resolved_label = label_text or target_label
    explicit_sort_order = sort_order is not None
    if sort_order is None:
        sort_order = batch.items.count()
    item, created = QrPrintBatchItem.objects.get_or_create(
        batch=batch,
        qr_code=qr,
        defaults={
            "label_text": resolved_label,
            "target_type": qr.target_type,
            "target_id": qr.target_id,
            "sort_order": sort_order,
        },
    )
    if created:
        audit.record(actor, "qr_print_batch_item.created", makerspace=batch.makerspace, target=item)
    else:
        values = {
            "label_text": resolved_label,
            "target_type": qr.target_type,
            "target_id": qr.target_id,
        }
        if explicit_sort_order:
            values["sort_order"] = sort_order
        update_fields = [field for field, value in values.items() if getattr(item, field) != value]
        if update_fields:
            for field in update_fields:
                setattr(item, field, values[field])
            item.save(update_fields=update_fields)
            audit.record(actor, "qr_print_batch_item.updated", makerspace=batch.makerspace, target=item)
    return item


def _create_asset_qr(actor, asset):
    qr, _ = QrCode.objects.get_or_create(
        makerspace=asset.makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id=asset.id,
        status=QrCode.Status.ACTIVE,
        defaults={"created_by": actor},
    )
    return qr


def _assets_missing_active_qr(product, limit):
    asset_ids_with_qr = QrCode.objects.filter(
        makerspace=product.makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id__in=product.assets.values("id"),
        status=QrCode.Status.ACTIVE,
    ).values("target_id")
    return list(
        product.assets.select_for_update()
        .exclude(id__in=asset_ids_with_qr)
        .order_by("created_at", "id")[:limit]
    )


def generate_assets_with_qr(actor, product, data, *, native=False):
    if len(data.get("name_prefix") or "") > 154:
        raise ValidationError({"name_prefix": "Ensure this field has no more than 154 characters."})
    if any(len(serial) > 100 for serial in data.get("serial_numbers") or []):
        raise ValidationError({"serial_numbers": "Each serial number must have no more than 100 characters."})
    actor = current_qr_actor(actor, native=native, makerspace_ids=[product.makerspace_id])
    initial = get_object_or_404(
        rbac.scope_by_action(actor, rbac.Action.MANAGE_QR, InventoryProduct.objects.all()),
        pk=product.pk, makerspace_id=product.makerspace_id,
    )
    created = []
    with qr_write([initial.makerspace_id]):
        # Makerspace row before the product row: the module_install lock order. Here so
        # /control/'s generate action is gated exactly like the API route.
        require_module_locked(product.makerspace_id, "asset_units")
        if data.get("print_batch_id") or data.get("create_print_batch"):
            require_module_locked(product.makerspace_id, "qr_print_batches")
        actor = current_qr_actor(actor, native=native, makerspace_ids=[initial.makerspace_id])
        product = get_object_or_404(
            rbac.scope_by_action(actor, rbac.Action.MANAGE_QR, InventoryProduct.objects.select_for_update()),
            pk=initial.pk, makerspace_id=initial.makerspace_id,
        )
        actor = current_qr_actor(actor, native=native, makerspace_ids=[initial.makerspace_id])
        if not rbac.can(actor, rbac.Action.MANAGE_QR, initial.makerspace_id):
            raise PermissionDenied()
        if product.tracking_mode != TrackingMode.INDIVIDUAL:
            # Converting is an inventory edit, not a QR action: MANAGE_QR alone may only
            # add units to a product that is already individual-tracked.
            if not rbac.can(actor, rbac.Action.EDIT_INVENTORY, product.makerspace_id):
                raise PermissionDenied("Converting a product to unit tracking requires inventory edit access.")
            product = availability.change_tracking_mode(product, TrackingMode.INDIVIDUAL)

        batch = None
        if data.get("print_batch_id"):
            batch = get_object_or_404(
                QrPrintBatch, pk=data["print_batch_id"], makerspace_id=product.makerspace_id
            )
        elif data.get("create_print_batch"):
            batch = QrPrintBatch.objects.create(
                makerspace=product.makerspace,
                title=f"{product.name[:185]} unit QR labels",
                created_by=actor,
            )
        serials = data.get("serial_numbers") or []
        name_prefix = data.get("name_prefix") or product.name
        existing_count = product.assets.count()
        missing_qr_assets = _assets_missing_active_qr(product, data["count"])

        for asset in missing_qr_assets:
            qr = _create_asset_qr(actor, asset)
            if batch:
                add_qr_to_batch(actor, batch, qr, label_text=_label_with_suffix(name_prefix, f" {asset.asset_tag}"))
            created.append({"asset": asset, "qr": qr})

        remaining_count = data["count"] - len(missing_qr_assets)
        limits.check_quota(product.makerspace, "assets", adding=remaining_count)
        for idx in range(remaining_count):
            next_number = existing_count + idx + 1
            asset_tag = f"{product.slug if hasattr(product, 'slug') else product.id}-{next_number:04d}"
            asset = InventoryAsset.objects.create(
                makerspace=product.makerspace,
                product=product,
                box=product.box,
                asset_tag=asset_tag,
                serial_number=serials[idx] if idx < len(serials) else "",
                notes=f"{name_prefix} #{next_number}",
            )
            qr = _create_asset_qr(actor, asset)
            if batch:
                add_qr_to_batch(actor, batch, qr, label_text=_label_with_suffix(name_prefix, f" {next_number}"))
            created.append({"asset": asset, "qr": qr})

        availability.reconcile_individual_product_from_assets(product)
        audit.record(actor, "asset_units.generated", makerspace=product.makerspace, target=product, meta={"count": data["count"]})
    return created, batch


def mark_batch_printed(actor, batch):
    with transaction.atomic():
        require_module_locked(batch.makerspace_id, "qr_print_batches")
        locked = QrPrintBatch.objects.select_for_update().get(pk=batch.pk)
        # Only a draft batch can be marked printed: block re-printing and prevent an
        # archived batch from being silently unarchived back to printed.
        if locked.status != QrPrintBatch.Status.DRAFT:
            raise ValidationError(
                f"Only draft QR print batches can be marked printed (status: {locked.status})."
            )
        locked.status = QrPrintBatch.Status.PRINTED
        locked.printed_at = timezone.now()
        locked.save(update_fields=["status", "printed_at"])
        audit.record(actor, "qr_print_batch.printed", makerspace=locked.makerspace, target=locked)
        return locked
