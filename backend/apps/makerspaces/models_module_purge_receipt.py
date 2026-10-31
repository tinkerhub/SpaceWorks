"""Source-local, immutable module cleanup intent; no portable grants or FK edges."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models


class ModulePurgeReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_makerspace_id = models.PositiveBigIntegerField(editable=False)
    source_public_code = models.CharField(max_length=32, editable=False)
    source_created_at = models.DateTimeField(editable=False)
    module_key = models.CharField(max_length=40, editable=False)
    auth_generation = models.UUIDField(editable=False)
    schema_version = models.PositiveSmallIntegerField(default=1, editable=False)
    storage_origins = models.JSONField(editable=False)
    exact_keys = models.JSONField(editable=False)
    namespace_clauses = models.JSONField(editable=False)
    holder_sites = models.JSONField(editable=False)
    charge_obligations = models.JSONField(editable=False)
    rollback_bindings = models.JSONField(editable=False)
    graph_digest = models.CharField(max_length=64, editable=False)
    intent_created_at = models.DateTimeField(editable=False)
    graph_purged_at = models.DateTimeField(null=True, blank=True, editable=False)
    invalidated_at = models.DateTimeField(null=True, blank=True, editable=False)
    invalidation_reason = models.CharField(max_length=40, blank=True, editable=False)
    last_attempt_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_error_code = models.CharField(max_length=40, blank=True, editable=False)

    class Meta:
        ordering = ("-intent_created_at",)
        constraints = [models.UniqueConstraint(
            fields=("source_makerspace_id", "module_key"),
            condition=models.Q(invalidated_at__isnull=True),
            name="module_purge_active_authority_unique",
        )]

    def save(self, *args, **kwargs):
        from .module_purge_receipt_authority import validate_receipt, validate_transition

        validate_receipt(self)
        if not self._state.adding:
            previous = type(self).objects.using(kwargs.get("using") or self._state.db).get(pk=self.pk)
            validate_transition(previous, self)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Module purge authority must be retained indefinitely.")
