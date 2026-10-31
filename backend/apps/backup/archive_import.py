"""Register a host-authenticated disaster archive before restore supervision."""

from datetime import timedelta
import hmac
import os
import re
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit import services as audit
from apps.backup import storage
from apps.backup.digests import sha256_file
from apps.backup.full_format import FULL_FORMAT
from apps.backup.outer_manifest import _canonical_json
from apps.backup.models import BackupArchive, PlatformBackupSettings, RestoreOperation


def require_import_principal(actor):
    actor = User.objects.filter(pk=getattr(actor, "pk", None)).first()
    if not actor or not (
        actor.is_active
        and actor.access_status == User.AccessStatus.ACTIVE
        and not actor.must_change_password
        and (actor.is_superuser or actor.role == User.Role.SUPERADMIN)
    ):
        raise ValidationError("The importing principal must be an active eligible superadmin.")
    return actor


def import_disaster_archive(
    actor, encrypted_path, manifest, *, expected_sha256=None,
    bundle=None, manifest_file=None, continuity_secrets_file=None, prospective_record=None,
):
    actor = require_import_principal(actor)
    # Raw service callers must pass the same authenticated admission as the CLI.
    if not all((bundle, manifest_file, continuity_secrets_file)):
        raise ValidationError("Authenticated full bundle admission is required for import.")
    from apps.backup.import_preflight import validate_import_preflight, ImportPreflightError

    try:
        admission = validate_import_preflight(
            encrypted_file=encrypted_path, bundle=bundle, manifest_file=manifest_file,
            continuity_secrets_file=continuity_secrets_file, expected_sha256=expected_sha256,
            require_host_support=True, prospective_record=prospective_record,
        )
    except ImportPreflightError as exc:
        raise ValidationError(str(exc)) from exc
    if _canonical_json(admission.manifest) != _canonical_json(manifest):
        raise ValidationError("The imported manifest differs from authenticated admission.")
    manifest = admission.manifest
    if not isinstance(expected_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ) is None:
        raise ValidationError(
            "A valid expected sha256 digest is required "
            "(64 lowercase hexadecimal characters)."
        )
    try:
        archive_id = uuid.UUID(str(manifest["archive_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("The imported archive manifest has no valid archive id.") from exc
    if (
        manifest.get("format") != FULL_FORMAT
        or manifest.get("scope") != BackupArchive.Scope.DEPLOYMENT
    ):
        raise ValidationError("Only an authenticated signed full deployment archive can be imported.")
    if not manifest.get("age_encrypted"):
        raise ValidationError("The imported archive is not declared age-encrypted.")
    path = os.fspath(encrypted_path)
    size = os.path.getsize(path)
    if size <= 0:
        raise ValidationError("The imported archive is empty.")
    archive_sha256 = sha256_file(path)
    if not hmac.compare_digest(expected_sha256, archive_sha256):
        raise ValidationError("The imported archive sha256 does not match the expected digest.")
    if BackupArchive.objects.filter(pk=archive_id).exists():
        raise ValidationError("This archive is already registered on the target deployment.")
    object_key = f"backup-archives/deployment/{archive_id}.tar.age"
    storage.upload_archive(object_key, path)
    try:
        with transaction.atomic():
            retention = PlatformBackupSettings.load().retention_days
            archive = BackupArchive.objects.create(
                id=archive_id,
                scope=BackupArchive.Scope.DEPLOYMENT,
                requested_by=actor,
                status=BackupArchive.Status.AVAILABLE,
                object_key=object_key,
                manifest=manifest,
                size_bytes=size,
                archive_sha256=archive_sha256,
                age_encrypted=True,
                completed_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=retention),
            )
            audit.record(actor, "backup.archive_imported", target=archive)
            from apps.backup.restore_services import request_restore

            restore = request_restore(actor, archive, RestoreOperation.Kind.DISASTER)
    except Exception:
        storage.delete_archive(object_key)
        raise
    return restore
