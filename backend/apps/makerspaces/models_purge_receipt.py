"""Deployment-local cleanup authority surviving tenant graph deletion."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models


class PurgeReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_makerspace_id = models.PositiveBigIntegerField(editable=False)
    source_purge_started_at = models.DateTimeField(editable=False)
    auth_generation = models.UUIDField(editable=False)
    schema_version = models.PositiveSmallIntegerField(default=1, editable=False)
    storage_origins = models.JSONField(editable=False)
    exact_keys = models.JSONField(editable=False)
    namespace_prefixes = models.JSONField(editable=False)
    graph_purged_at = models.DateTimeField(editable=False)
    invalidated_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_attempt_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_error_code = models.CharField(max_length=40, blank=True, editable=False)

    class Meta:
        ordering = ("-graph_purged_at",)

    def save(self, *args, **kwargs):
        from .purge_receipt_authority import validate_receipt

        if self.last_error_code not in {"", "cleanup_unconfirmed"}:
            raise ValidationError("Unsupported purge receipt outcome code.")
        if self._state.adding:
            validate_receipt(self)
        else:
            previous = type(self).objects.using(kwargs.get("using") or self._state.db).get(pk=self.pk)
            mutable = {"last_attempt_at", "last_verified_at", "last_error_code", "invalidated_at"}
            if any(getattr(self, f.attname) != getattr(previous, f.attname)
                   for f in self._meta.concrete_fields if f.name not in mutable):
                raise ValidationError("Purge receipt authority is immutable.")
            if previous.invalidated_at is not None and self.invalidated_at != previous.invalidated_at:
                raise ValidationError("Purge receipt invalidation is irreversible.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Purge receipt locators must be retained indefinitely.")
