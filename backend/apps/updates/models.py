"""Retired in-app updater: only this model stays installed, for exactly one release.

Every surface (staff panel, admin API, /control/ page, update_control, module key) is gone;
releases now arrive through the GitHub release webhook. The model is kept because:
* a failed deploy rolls back to the previous image without running migrations, and that image
  needs its `updates` migration recorded and this table present to pass readiness;
* compound backups refuse any physical table that no installed model classifies.
A later release deletes this app and drops the table together (docs/PROJECT-STATUS.md).
"""

from django.db import models


class PlatformUpdateSettings(models.Model):
    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        FAILED = "failed", "Failed"

    automatic_updates_enabled = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.IDLE,
    )
    current_version = models.CharField(max_length=80, blank=True)
    available_version = models.CharField(max_length=80, blank=True)
    target_version = models.CharField(max_length=80, blank=True)
    update_requested_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_updated_at = models.DateTimeField(null=True, blank=True)
    last_backup_at = models.DateTimeField(null=True, blank=True)
    last_backup_name = models.CharField(max_length=120, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Platform update settings"
