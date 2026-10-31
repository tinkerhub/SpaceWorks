"""Best-effort cleanup for terminal certificate keys that were never activated."""

import logging
from functools import partial

from django.conf import settings
from django.db import transaction

from apps.backup.not_restored import TenantNotRestored
from apps.events import certificate_storage
from apps.events.models import EventAttendanceCertificate
from apps.object_storage import delete_all_versions
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from apps.tenant_migration.gate_runtime import boundary_tenant_write


logger = logging.getLogger(__name__)


def cleanup_abandoned_certificate(certificate_id):
    # Revoked is terminal and each revision has its own key. An issued artifact
    # remains retained and charged even after revocation; it is never ours to delete.
    try:
        artifact = EventAttendanceCertificate.objects.filter(
            pk=certificate_id,
            status=EventAttendanceCertificate.Status.REVOKED,
            rendered_at__isnull=True,
            size_bytes__isnull=True,
        ).values_list("object_key", "registration__event__makerspace_id").first()
        if artifact is None:
            return
        key, makerspace_id = artifact
        with boundary_tenant_write(makerspace_id):
            client = certificate_storage._client(settings.AWS_S3_ENDPOINT_URL)
            for object_key in (key, certificate_storage.staging_key(key)):
                try:
                    delete_all_versions(
                        client, bucket=settings.AWS_STORAGE_BUCKET_NAME, key=object_key,
                    )
                except Exception:
                    logger.exception(
                        "event_certificate_abandoned_cleanup_failed",
                        extra={"certificate_id": certificate_id},
                    )
    except (SourceMigrationGateClosed, TenantNotRestored):
        logger.info(
            "event_certificate_cleanup_skipped_closed_source_gate",
            extra={"certificate_id": certificate_id},
        )
    except Exception:
        logger.exception(
            "event_certificate_abandoned_cleanup_failed",
            extra={"certificate_id": certificate_id},
        )


def cleanup_abandoned_certificate_on_commit(certificate_id):
    # Also used by a revoked worker after upload: the revoke callback may have
    # run before that worker wrote its final/staging objects. Never do S3 I/O
    # while a surrounding workflow still holds its database row locks.
    from apps.makerspaces.purge_cleanup import owns_cleanup

    makerspace_id = EventAttendanceCertificate.objects.filter(pk=certificate_id).values_list(
        "registration__event__makerspace_id", flat=True,
    ).first()
    if makerspace_id is not None and owns_cleanup(makerspace_id):
        return
    transaction.on_commit(partial(cleanup_abandoned_certificate, certificate_id))
