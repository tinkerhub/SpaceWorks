from contextlib import nullcontext

from django.db import IntegrityError, transaction
from apps.object_storage_lifecycle import storage_lifecycle
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from django.utils.text import slugify

from apps.admin_api.bulk_import_preview import preview_import
from apps.admin_api.bulk_import_rows import QUANTITY_BUCKET_FIELDS, find_category
from apps.audit import services as audit
from apps.boxes.models import Box
from apps.evidence.storage import StorageUnavailable
from apps.inventory import availability, public_image_storage
from apps.inventory.models import Category, InventoryProduct
from apps.inventory.public_image_attach import PublicImageRejected, finalize_product_image
from apps.makerspaces import limits


def apply_import(actor, makerspace, rows, mapping, progress_callback=None, allow_partial=False):
    with boundary_tenant_write(makerspace.pk):
        preview = preview_import(makerspace, rows, mapping, progress_callback)
        if not preview["valid"] and not allow_partial:
            return {**preview, "applied": False}
        context = storage_lifecycle(makerspace.pk) if any(
            item["action"] != "error" and item["data"].get("image_key", "")
            for item in preview["rows"]
        ) else nullcontext(None)
        with context as guard:
            prepared = {}
            for item in preview["rows"]:
                key = item["data"].get("image_key", "")
                if item["action"] == "error" or not key:
                    continue
                product = InventoryProduct.objects.filter(makerspace=makerspace, name=item["data"]["name"]).first()
                try:
                    prepared[item["row"]] = finalize_product_image(
                        makerspace.pk, key, product_id=product.pk if product else None,
                    )
                except (PublicImageRejected, StorageUnavailable) as exc:
                    _record_row_error(preview, item, "Image storage is unavailable." if isinstance(exc, StorageUnavailable) else str(exc))
            # Image preparation failures keep the existing per-row runtime-error policy.
            # Only the initial parser preview above controls allow_partial admission.
            created = 0
            updated = 0
            if guard is not None:
                guard.verify()
            with transaction.atomic():
                import_names = {
                    item["data"]["name"]
                    for item in preview["rows"]
                    if item["action"] != "error"
                }
                existing_names = set(
                    InventoryProduct.objects.filter(
                        makerspace=makerspace,
                        name__in=import_names,
                    ).values_list("name", flat=True)
                )
                limits.check_quota(
                    makerspace,
                    "products",
                    adding=len(import_names - existing_names),
                )
                for item in preview["rows"]:
                    if item["action"] == "error":
                        continue
                    try:
                        with transaction.atomic():
                            was_created = _apply_import_row(
                                actor, makerspace, item, preview["mapping"], prepared.get(item["row"]), guard
                            )
                    except IntegrityError as exc:
                        _record_row_error(preview, item, _short_db_message(exc))
                        continue
                    except (
                        availability.TrackingModeChangeRefused,
                        PublicImageRejected,
                    ) as exc:
                        _record_row_error(preview, item, str(exc))
                        continue
                    except StorageUnavailable:
                        _record_row_error(preview, item, "Image storage is unavailable.")
                        continue
                    if was_created:
                        created += 1
                    else:
                        updated += 1
                audit.record(
                    actor,
                    "inventory.bulk_imported",
                    makerspace=makerspace,
                    target=makerspace,
                    meta={"created": created, "updated": updated},
                )
            _refresh_summary(preview)
            return {
                **preview,
                "applied": True,
                "partial": bool(preview["errors"]),
                "created": created,
                "updated": updated,
            }


def _apply_import_row(actor, makerspace, item, mapping, prepared_size, guard):
    data = dict(item["data"])
    box_id = data.pop("box_id", None)
    box = Box.objects.filter(makerspace=makerspace, pk=box_id).first() if box_id else None
    name = data.pop("name")
    image_key = data.pop("image_key", "")
    category_name = data.pop("category_name", "")
    if category_name:
        category, was_category_created = _category_for_name(makerspace, category_name)
        data["category_id"] = category.id
        if was_category_created:
            audit.record(
                actor,
                "category.created",
                makerspace=makerspace,
                target=category,
                meta={"source": "bulk_import"},
            )
    product, was_created = InventoryProduct.objects.get_or_create(
        makerspace=makerspace, name=name, defaults={**data, "box": box}
    )
    if was_created:
        _attach_image(makerspace, product, image_key, prepared_size, guard)
        return True
    tracking_mode = data.pop("tracking_mode")
    if mapping.get("tracking_mode"):
        # Only a mapped column changes the mode, and only through the Availability
        # module's guarded path; the parser's default must never convert a product.
        product = availability.change_tracking_mode(product, tracking_mode)
    update_defaults = {
        field: value for field, value in data.items() if field not in QUANTITY_BUCKET_FIELDS
    }
    update_defaults["box"] = box
    for field, value in update_defaults.items():
        setattr(product, field, value)
    product.save(update_fields=[*update_defaults.keys(), "updated_at"])
    _attach_image(makerspace, product, image_key, prepared_size, guard)
    return False


def _attach_image(makerspace, product, image_key, prepared_size, guard):
    """Attach an imported key through the image endpoint's finalize/sniff pipeline.

    A blank cell keeps the current image instead of silently dropping it."""
    if not image_key or image_key == product.image_key:
        return
    if public_image_storage.public_image_key_in_use(makerspace.pk, image_key, product_id=product.pk):
        raise PublicImageRejected("This image is already in use.")
    guard.verify(makerspace.pk)
    size = prepared_size
    limits.add_storage(makerspace, size)
    if product.image_key:
        public_image_storage.release_public_image_on_commit(makerspace, product.image_key, guard=guard)
    product.image_key = image_key
    product.save(update_fields=["image_key", "updated_at"])


def _record_row_error(preview, item, message):
    item["action"] = "error"
    preview["errors"].append({"row": item["row"], "errors": {"__all__": message}})
    preview["valid"] = False


def _short_db_message(exc):
    message = str(exc).strip()
    if not message:
        return "Database integrity error."
    return message.splitlines()[0][:240]


def _refresh_summary(preview):
    rows = preview["rows"]
    preview["summary"] = {
        **preview["summary"],
        "create": sum(1 for item in rows if item["action"] == "create"),
        "update": sum(1 for item in rows if item["action"] == "update"),
        "errors": len(preview["errors"]),
        "warnings": len(preview["warnings"]),
        "total": len(rows),
    }


def _category_for_name(makerspace, name):
    base_slug = slugify(name) or "category"
    slug = base_slug
    for _attempt in range(2):
        category = find_category(makerspace, name)
        if category:
            return category, False
        slug = base_slug
        suffix = 2
        while Category.objects.filter(makerspace=makerspace, slug=slug).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        try:
            with transaction.atomic():
                return Category.objects.create(makerspace=makerspace, name=name, slug=slug), True
        except IntegrityError:
            continue
    category = find_category(makerspace, name)
    if category:
        return category, False
    with transaction.atomic():
        return Category.objects.create(makerspace=makerspace, name=name, slug=slug), True
