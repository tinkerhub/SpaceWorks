"""Irreversible purge authority, persisted independently of external deletion."""

import hashlib
import json
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed


class PurgeInProgress(SourceMigrationGateClosed):
    code = "makerspace_purge_started"


class PurgePending(ValidationError):
    def __init__(self, not_before):
        self.not_before = not_before
        super().__init__(f"Purge intent committed. Retry after {not_before.isoformat()}.")


def assert_not_purging(makerspace_id):
    if Makerspace.objects.filter(pk=makerspace_id, purge_started_at__isnull=False).exists():
        raise PurgeInProgress("Purge has started; this makerspace cannot accept writes or reopen.")


def assert_capture_allowed(makerspace_ids=None):
    from .module_purge_state import assert_no_inprogress

    if makerspace_ids is not None:
        makerspace_ids = tuple(makerspace_ids)
    try:
        assert_no_inprogress(makerspace_ids)
    except ValidationError as exc:
        raise PurgeInProgress("An unfinished module purge intent prevents archive capture.") from exc
    query = Makerspace.objects.filter(purge_started_at__isnull=False)
    if makerspace_ids is not None:
        query = query.filter(pk__in=makerspace_ids)
    if query.exists():
        raise PurgeInProgress(
            "Archive capture includes a purge-started makerspace. Finish purge or restore a pre-purge archive."
        )


def require_actor(actor):
    if not (
        getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_superuser", False)
        and getattr(actor, "is_active", False)
        and getattr(actor, "is_staff", False)
        and not getattr(actor, "is_tenant_dump_stub", False)
        and getattr(actor, "access_status", None) == "active"
        and not getattr(actor, "must_change_password", True)
    ):
        raise ValidationError("Purge requires an active, unrestricted superuser.")


def require_purgeable(makerspace):
    if makerspace.archived_at is None:
        raise ValidationError("Cannot purge a makerspace that is not archived.")
    if not makerspace.superadmin_access_enabled:
        raise ValidationError("Cannot purge a hidden makerspace.")
    if makerspace.lifecycle_state != Makerspace.LifecycleState.ACTIVE:
        raise ValidationError("Cannot purge an importing or aborted makerspace.")


def storage_origins():
    # Credentials never enter the fingerprint payload. Browser origin matters too:
    # issued presigns may still be directed there after a backend setting changes.
    endpoints = []
    for name in ("AWS_S3_ENDPOINT_URL", "AWS_S3_PUBLIC_ENDPOINT_URL"):
        raw = getattr(settings, name, None)
        if not raw:
            endpoints.append(["aws", settings.AWS_S3_REGION_NAME])
            continue
        url = urlsplit(raw)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.query or url.fragment):
            raise ValidationError("Storage origin cannot be safely identified.")
        endpoints.append([
            url.scheme.lower(), url.hostname.lower(),
            url.port or (443 if url.scheme == "https" else 80), url.path.rstrip("/"),
        ])
    result = {}
    for kind, bucket in (
        ("private", settings.AWS_STORAGE_BUCKET_NAME),
        ("public_image", settings.PUBLIC_IMAGE_BUCKET),
    ):
        if not isinstance(bucket, str) or not bucket:
            raise ValidationError("Storage bucket identity is missing.")
        payload = json.dumps([endpoints, bucket], separators=(",", ":"), sort_keys=True)
        result[kind] = hashlib.sha256(payload.encode()).hexdigest()
    return result


def commit_intent(makerspace_id, actor, *, expected_slug):
    require_actor(actor)
    with transaction.atomic(durable=True):
        space = Makerspace.objects.select_for_update().get(pk=makerspace_id)
        require_purgeable(space)
        if space.slug != expected_slug:
            raise ValidationError("The makerspace slug changed; confirm the current slug before retrying.")
        if space.purge_started_at is None:
            now = timezone.now()
            seconds = max(0, *[
                int(getattr(settings, name)) for name in (
                    "EVIDENCE_URL_TTL_SECONDS", "PUBLIC_IMAGE_URL_TTL_SECONDS",
                    "PRINT_URL_TTL_SECONDS", "TENANT_MIGRATION_PRESIGN_DRAIN_SECONDS",
                    "BACKUP_PRESIGN_DRAIN_SECONDS",
                )
            ]) + 60
            meta = {
                "makerspace_id": space.pk, "name": space.name, "slug": space.slug,
                "purge_started_at": now.isoformat(),
                "not_before": (now + timedelta(seconds=seconds)).isoformat(),
                "storage_origins": storage_origins(), "purge_intent_version": 1,
            }
            space.purge_started_at = now
            space.save(update_fields=["purge_started_at"])
            audit.record(actor, "makerspace.purge_started", meta=meta)
        return space, load_intent(space)


def load_intent(space):
    if space.purge_started_at is None:
        raise ValidationError("Purge intent is missing.")
    records = list(AuditLog.objects.filter(
        makerspace__isnull=True, action="makerspace.purge_started",
        meta__makerspace_id=space.pk,
        meta__purge_started_at=space.purge_started_at.isoformat(),
    ).values_list("meta", flat=True)[:2])
    if len(records) != 1:
        raise ValidationError("Purge intent audit is missing or ambiguous.")
    meta = records[0]
    try:
        not_before = parse_datetime(meta["not_before"])
        valid = (meta["purge_intent_version"] == 1 and not_before is not None
                 and timezone.is_aware(not_before)
                 and not_before >= space.purge_started_at
                 and meta["storage_origins"] == storage_origins())
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValidationError("Purge deadline or storage origin proof is invalid or changed.")
    return meta
