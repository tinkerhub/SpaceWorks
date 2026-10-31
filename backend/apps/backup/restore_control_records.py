"""Persist supervisor facts outside a database that is about to be replaced."""

import json
from datetime import timedelta
from pathlib import Path

import logging

from django.core.management import call_command
from django.db import connection, transaction
from django.utils import timezone

from apps.backup import storage
from apps.backup.full_format import FULL_FORMAT
from apps.backup.full_control_record import (
    apply_archive_record, capture_archive_record, validate_archive_record, write_private_json,
)
from apps.backup.full_restore_identity import capture_target_identity, verify_target_identity
from apps.backup.manifest_dispatch import registered_manifest_kind, verify_signed_manifest
from apps.backup.models import (
    BackupArchive,
    DeploymentRecoveryState,
    PlatformBackupSettings,
    RestoreOperation,
)

logger = logging.getLogger(__name__)


def export_control_record(restore_id, output, decision=None):
    restore = RestoreOperation.objects.get(pk=restore_id)
    payload = {
        "decision": decision or restore.decision,
        "restore_diff": restore.restore_diff,
        "decision_deadline_at": (
            restore.decision_deadline_at.isoformat()
            if restore.decision_deadline_at else None
        ),
        "fencing_token": str(restore.fencing_token or ""),
        "requested_by_username": restore.requested_by_username_snapshot,
    }
    if restore.archive.manifest.get("format") == FULL_FORMAT:
        registered_manifest_kind(restore.archive.manifest, restore.archive.manifest)
        with transaction.atomic():
            payload["full_target_identity"] = capture_target_identity(connection.connection)
        payload["full_archive_identity"] = capture_archive_record(restore.archive)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True)
    if "full_target_identity" in payload:
        from apps.backup.full_restore_identity import MAX_CONTROL_BYTES

        # The all-table report may be large; the privileged bootstrap receives
        # only its bounded identity projection, never the report itself.
        identity = {"full_target_identity": payload["full_target_identity"]}
        if len(json.dumps(identity).encode("utf-8")) > MAX_CONTROL_BYTES:
            raise RuntimeError("The signed-full target identity exceeds its size bound.")
        write_private_json(path, payload)
        write_private_json(path.with_name(f"{path.name}.identity.json"), identity)
    else:
        path.write_text(encoded, encoding="utf-8")
    return path


@transaction.atomic
def rehydrate_control_record(restore_id, options):
    from apps.accounts.models import User

    control = json.loads(Path(options["control_record"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8"))
    if manifest.get("format") == FULL_FORMAT:
        verify_signed_manifest(manifest)
        archive_record = validate_archive_record(
            control.get("full_archive_identity"), manifest, options["archive_id"],
        )
        verify_target_identity(connection.connection, control.get("full_target_identity"))
    elif "full_target_identity" in control:
        raise RuntimeError("The target identity control record requires signed-full restore.")
    completed_at = timezone.now()
    archive = BackupArchive.objects.select_for_update().get(
        pk=options["archive_id"]
    )
    archive.status = BackupArchive.Status.AVAILABLE
    archive.manifest = manifest
    archive.age_encrypted = True
    archive.completed_at = completed_at
    archive.failure_detail = ""
    if archive.expires_at is None:
        archive.expires_at = completed_at + timedelta(
            days=PlatformBackupSettings.load().retention_days
        )
    if manifest.get("format") == FULL_FORMAT:
        apply_archive_record(archive, archive_record)
    archive.save(
        update_fields=(
            "status",
            "manifest",
            "age_encrypted",
            "completed_at",
            "failure_detail",
            "expires_at",
            "archive_sha256",
            "size_bytes",
            "object_key",
            "download_token_digest",
            "download_token_expires_at",
            "download_token_consumed_at",
            "updated_at",
        )
    )
    transaction.on_commit(
        lambda: storage.delete_archive_prefix(
            f"backup-archives/staging/{archive.pk}/"
        )
    )
    requested_by = User.objects.filter(
        username=control.get("requested_by_username", "")
    ).first()
    restore, _ = RestoreOperation.objects.update_or_create(
        pk=restore_id,
        defaults={
            "archive_id": options["archive_id"],
            "kind": options["kind"],
            "requested_by": requested_by,
            "requested_by_username_snapshot": control.get("requested_by_username", ""),
            "stage": RestoreOperation.Stage.DB_RESTORING,
            "decision": control["decision"],
            "restore_diff": control.get("restore_diff") or {},
            "decision_deadline_at": control.get("decision_deadline_at"),
            "fencing_token": control.get("fencing_token") or None,
        },
    )
    state = DeploymentRecoveryState.load()
    state.mode = DeploymentRecoveryState.Mode.QUIESCED
    state.active_restore = restore
    state.save(update_fields=("mode", "active_restore", "updated_at"))
    return restore


def validate_restored_state(restore_id):
    restore = RestoreOperation.objects.get(pk=restore_id)
    if restore.stage != RestoreOperation.Stage.VALIDATING:
        raise RuntimeError("Only the validating stage can run restored-state checks.")
    from django.conf import settings
    from apps.backup.host_marker import MarkerState, read_marker
    from apps.backup.inplace_readiness import assert_inplace_ready

    marker = read_marker(getattr(settings, "SPACEWORKS_HOST_MARKER_PATH",
                                 "/run/spaceworks-host/restore-marker.json"))
    if marker.state == MarkerState.RESTORE_BLOCKED:
        assert_inplace_ready(marker, restore)
    call_command("check", verbosity=0)
    from apps.accounts.token_guard import validate_token_configuration
    from apps.backup.custody import validate_deployment_custody
    from apps.backup.route_guard import validate_recovery_route_allowlists
    from apps.encryption.readiness import assert_ready

    assert_ready()
    # `validate_deployment_custody` has already PERSISTED each makerspace's custody
    # state in deterministic order, so the alarm exists before we decide anything.
    custody = validate_deployment_custody()
    if custody.zero_recipient_off_makerspace_ids:
        # Deliberately NOT fatal. Zero recipients is an explicitly supported state --
        # a compromise always proceeds even when it breaches the floor -- so aborting
        # here would make every deployment archive containing such a tenant
        # unrestorable, with no repair path (quarantine blocks acknowledgement and
        # exposes no recipient management). Refusing the restore does not fix the
        # tenant's custody posture; it only prevents recovery.
        # The fail-closed rule belongs on the BUILD side, where `selection_for`
        # already refuses to encrypt an archive to nobody.
        logger.error(
            "restore_zero_recipient_self_governed_makerspaces",
            extra={"makerspace_ids": list(custody.zero_recipient_off_makerspace_ids)},
        )
    validate_token_configuration()
    validate_recovery_route_allowlists()
