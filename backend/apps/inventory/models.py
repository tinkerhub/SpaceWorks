from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import DEFERRED

from apps.makerspaces.models import Makerspace


class PublicAvailabilityMode(models.TextChoices):
    EXACT_COUNT = "exact_count", "Exact Count"
    STATUS_ONLY = "status_only", "Status Only"
    HIDDEN = "hidden", "Hidden"


class TrackingMode(models.TextChoices):
    QUANTITY = "quantity", "Quantity"
    INDIVIDUAL = "individual", "Individual"


class Category(models.Model):
    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="categories",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120)
    display_order = models.PositiveIntegerField(default=0)
    icon = models.CharField(max_length=50, blank=True)
    # The category part of an item code (MCU in TC-MCU-A); see `apps.inventory.item_codes`.
    code = models.CharField(
        max_length=4,
        blank=True,
        default="",
        validators=[RegexValidator(r"^[A-Z]{2,4}$", "Use 2–4 capital letters, e.g. MCU.")],
    )
    # How many item letters this category has issued. Letters are never reused, so only
    # `item_codes.issue_letter` writes it (see save()).
    code_sequence = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "slug"],
                name="uniq_category_slug_per_makerspace",
            ),
            models.UniqueConstraint(
                fields=["makerspace", "code"],
                condition=~models.Q(code=""),
                name="uniq_category_code_per_makerspace",
            ),
        ]
        ordering = ["display_order", "name"]
        verbose_name_plural = "Categories"

    def __str__(self) -> str:
        return f"{self.name} [{self.makerspace.slug}]"

    def save(self, *args, **kwargs):
        # A full save of a loaded row would write back the counter it was loaded with and
        # undo letters issued since, so an update never touches it unless named.
        if not self._state.adding and kwargs.get("update_fields") is None and not kwargs.get("force_insert"):
            kwargs["update_fields"] = [
                field.name
                for field in self._meta.concrete_fields
                if not field.primary_key and field.name != "code_sequence"
            ]
        super().save(*args, **kwargs)


class InventoryProduct(models.Model):
    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="products",
    )
    box = models.ForeignKey(
        "boxes.Box",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    category = models.ForeignKey(
        "Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    name = models.CharField(max_length=200)
    # The letter part of the item code (A in TC-MCU-A), issued per category.
    code_letter = models.CharField(max_length=4, blank=True, default="", editable=False)
    description = models.TextField(blank=True)
    image_key = models.CharField(max_length=300, blank=True, default="")
    # Individual-mode availability still derives from the quantity buckets until the
    # Unit service layer (Phase 6); tracking_mode is just a classification flag for now.
    tracking_mode = models.CharField(
        max_length=20,
        choices=TrackingMode.choices,
        default=TrackingMode.QUANTITY,
    )
    total_quantity = models.PositiveIntegerField(default=0)
    available_quantity = models.PositiveIntegerField(default=0)
    reserved_quantity = models.PositiveIntegerField(default=0)
    issued_quantity = models.PositiveIntegerField(default=0)
    damaged_quantity = models.PositiveIntegerField(default=0)
    lost_quantity = models.PositiveIntegerField(default=0)
    # Units pulled out of circulation for repair (e.g. rejected as broken at handover).
    # Counted within total but never available, so the usable count drops until repaired.
    needs_fix_quantity = models.PositiveIntegerField(default=0)
    is_public = models.BooleanField(default=True)
    public_self_checkout_enabled = models.BooleanField(default=False)
    show_public_count = models.BooleanField(default=False)
    public_availability_mode = models.CharField(
        max_length=20,
        choices=PublicAvailabilityMode.choices,
        default=PublicAvailabilityMode.STATUS_ONLY,
    )
    storage_location = models.CharField(max_length=200, blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Inventory item"
        verbose_name_plural = "Inventory"
        indexes = [
            models.Index(fields=["makerspace", "is_public", "is_archived"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_quantity__gte=0),
                name="qty_total_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(available_quantity__gte=0),
                name="qty_available_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_quantity__gte=0),
                name="qty_reserved_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(issued_quantity__gte=0),
                name="qty_issued_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(damaged_quantity__gte=0),
                name="qty_damaged_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(lost_quantity__gte=0),
                name="qty_lost_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(needs_fix_quantity__gte=0),
                name="qty_needs_fix_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    total_quantity__gte=(
                        models.F("available_quantity")
                        + models.F("reserved_quantity")
                        + models.F("issued_quantity")
                        + models.F("damaged_quantity")
                        + models.F("lost_quantity")
                        + models.F("needs_fix_quantity")
                    )
                ),
                name="qty_sum_within_total",
            ),
            models.UniqueConstraint(
                fields=["makerspace", "category", "code_letter"],
                condition=~models.Q(code_letter=""),
                name="uniq_product_code_letter_per_category",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.makerspace.slug})"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        # The category the row was loaded with, so save() can tell a move from a re-save.
        instance._loaded_category_id = instance.__dict__.get("category_id", DEFERRED)
        return instance

    def save(self, *args, **kwargs):
        from apps.inventory.item_codes import sync_code_letter

        update_fields = kwargs.get("update_fields")
        if sync_code_letter(self, update_fields) and update_fields is not None:
            kwargs["update_fields"] = [*update_fields, "code_letter"]
        super().save(*args, **kwargs)
        self._loaded_category_id = self.category_id

    @property
    def item_code(self) -> str:
        from apps.inventory.item_codes import item_code

        return item_code(self)

    def clean(self):
        if self.box_id and self.box.makerspace_id != self.makerspace_id:
            raise ValidationError(
                {"box": "Box must belong to the same makerspace as the product."}
            )
        if self.category_id and self.category.makerspace_id != self.makerspace_id:
            raise ValidationError(
                {"category": "Category must belong to the same makerspace."}
            )


class InventoryAsset(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        ISSUED = "issued", "Issued"
        DAMAGED = "damaged", "Damaged"
        LOST = "lost", "Lost"
        RETIRED = "retired", "Retired"
        MAINTENANCE = "maintenance", "Maintenance"

    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="assets",
    )
    product = models.ForeignKey(
        InventoryProduct,
        on_delete=models.CASCADE,
        related_name="assets",
    )
    box = models.ForeignKey(
        "boxes.Box",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assets",
    )
    asset_tag = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_index=True,
    )
    public_self_checkout_enabled = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "asset_tag"],
                name="uniq_asset_tag_per_makerspace",
            ),
        ]
        indexes = [
            models.Index(fields=["makerspace", "status"]),
        ]

    def clean(self):
        errors = {}
        if self.product_id and self.product.makerspace_id != self.makerspace_id:
            errors["product"] = "Product must belong to the same makerspace."
        if self.box_id and self.box.makerspace_id != self.makerspace_id:
            errors["box"] = "Box must belong to the same makerspace."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.asset_tag} ({self.makerspace.slug})"
