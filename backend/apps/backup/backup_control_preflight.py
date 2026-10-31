"""Preflight routing for legacy and compound deployment restore paths."""

import os
from pathlib import Path
import shutil

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connections
from django.utils import timezone

from apps.backup import storage
from apps.backup.digests import (
    ArchiveDigestError,
    SUPPORTED_ARCHIVE_FORMATS,
    verify_content_ledger,
)
from apps.backup.import_preflight import (
    ImportPreflightError,
    validate_import_preflight,
)
from apps.backup.models import BackupArchive, RestoreOperation
from apps.backup.errors import BackupBuildError
from apps.backup.full_format import FULL_FORMAT, COMPOUND_UNSUPPORTED
from apps.backup.full_bundle import verify_full_root
from apps.backup.manifest_dispatch import registered_manifest_kind
from apps.backup.restore_services import set_stage


# The v1/v2 builders predate the routing field; absence means a full legacy
# archive. V3 and later manifests must declare the boolean explicitly.
_FORMATS_WITHOUT_PARTIAL_DECLARATION = frozenset({
    "spaceworks-phase5a-v1",
    "spaceworks-phase5a-v2",
})


def run_restore_preflight(
    restore_id,
    manifest_path,
    *,
    current_oci_digest,
    bundle_path,
    encrypted_file,
    decrypted_bundle,
    continuity_secrets,
    build_info,
    check_setting_policies,
    prospective_record=None,
):
    restore = RestoreOperation.objects.select_related("archive").get(pk=restore_id)
    archive = restore.archive
    if (
        archive.status != BackupArchive.Status.AVAILABLE
        or archive.expires_at is None
        or archive.expires_at <= timezone.now()
        or not archive.age_encrypted
    ):
        raise CommandError(
            "The selected archive is not a completed age-encrypted deployment backup."
        )
    try:
        from apps.backup.import_preflight_bundle import read_json_file

        manifest = read_json_file(manifest_path, "manifest")
    except (OSError, ImportPreflightError) as exc:
        raise CommandError("The authenticated archive manifest is unreadable.") from exc
    try:
        kind = registered_manifest_kind(archive.manifest, manifest)
    except (BackupBuildError, TypeError, ValueError) as exc:
        raise CommandError(str(exc)) from exc
    if kind == "compound":
        raise CommandError(COMPOUND_UNSUPPORTED)
    format_name = manifest.get("format")
    partial = manifest.get("partial")
    if (
        "partial" not in manifest
        and format_name in _FORMATS_WITHOUT_PARTIAL_DECLARATION
    ):
        partial = False
    if (
        format_name not in SUPPORTED_ARCHIVE_FORMATS | {FULL_FORMAT}
        or manifest.get("scope") != BackupArchive.Scope.DEPLOYMENT
        or manifest.get("archive_id") != str(archive.pk)
        or manifest.get("age_encrypted") is not True
        or partial is not False
    ):
        raise CommandError(
            "The authenticated archive manifest does not match the restore intent."
        )
    if kind == "full":
        _validate_full(
            archive, manifest, manifest_path=manifest_path, bundle_path=bundle_path,
            encrypted_file=encrypted_file, decrypted_bundle=decrypted_bundle,
            continuity_secrets=continuity_secrets, prospective_record=prospective_record,
            restore_id=restore_id,
        )
    environment = None
    if prospective_record:
        if kind != "full":
            raise CommandError("Prospective compatibility requires signed-full admission.")
        from apps.backup.restore_prospective import prospective_environment

        environment = prospective_environment(
            prospective_record, manifest=manifest, archive_sha256=archive.archive_sha256,
            continuity_file=continuity_secrets, restore_id=restore_id,
        )
    _validate_legacy(
        restore,
        manifest,
        bundle_path=bundle_path,
        current_oci_digest=current_oci_digest,
        build_info=build_info,
        check_setting_policies=check_setting_policies, environment=environment,
    )
    if restore.stage == RestoreOperation.Stage.CLAIMED:
        set_stage(restore_id, RestoreOperation.Stage.PREFLIGHT)
    return "full-preflight-ok" if kind == "full" else "preflight-ok"


def _validate_full(
    archive, manifest, *, encrypted_file, decrypted_bundle, manifest_path,
    continuity_secrets, bundle_path, prospective_record=None, restore_id=None,
):
    if not all((encrypted_file, decrypted_bundle, continuity_secrets, bundle_path)):
        raise CommandError("Signed full restore requires encrypted, tar, extracted and continuity inputs.")
    try:
        result = validate_import_preflight(
            encrypted_file=encrypted_file, bundle=decrypted_bundle,
            manifest_file=manifest_path, continuity_secrets_file=continuity_secrets,
            expected_sha256=archive.archive_sha256 or None,
            require_host_support=True, prospective_record=prospective_record, restore_id=restore_id,
        )
        if result.manifest != manifest:
            raise BackupBuildError("The full restore received a different manifest.")
        verify_full_root(bundle_path, manifest)
    except (ImportPreflightError, BackupBuildError) as exc:
        raise CommandError(str(exc)) from exc


def _validate_legacy(
    restore, manifest, *, bundle_path, current_oci_digest, build_info,
    check_setting_policies, environment=None,
):
    from apps.backup.restore_manifest_facts import (
        RestoreManifestFactsError, validate_restore_object_facts,
    )

    try:
        validate_restore_object_facts(manifest, bundle_path)
    except RestoreManifestFactsError as exc:
        raise CommandError(str(exc)) from exc
    if bundle_path:
        try:
            verify_content_ledger(
                bundle_path,
                manifest.get("contents"),
                require_ledger=manifest.get("format") in {
                    "spaceworks-phase5a-v2", "spaceworks-phase5a-v3", FULL_FORMAT,
                },
            )
        except ArchiveDigestError as exc:
            raise CommandError(str(exc)) from exc
    source_major = manifest.get("postgres", {}).get("source_server_major")
    with connections["default"].cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        target_major = int(cursor.fetchone()[0]) // 10000
    if (
        type(source_major) is not int
        or source_major not in {14, 15, 16, 17}
        or target_major < source_major
    ):
        raise CommandError(
            f"Unsupported PostgreSQL restore: source={source_major}, target={target_major}."
        )
    ops = Path(settings.BACKUP_OPS_DIR)
    if not ops.is_dir() or not os.access(ops, os.R_OK | os.W_OK | os.X_OK):
        raise CommandError(
            "The shared host operation mount is unavailable; legacy in-place restore is excluded."
        )
    for command in ("age", "pg_restore", "pg_dump"):
        if shutil.which(command) is None:
            raise CommandError(f"Required restore binary is missing: {command}.")
    archived_build = manifest.get("build", {})
    current_build = build_info()
    if archived_build.get("source_hash") != current_build.get("source_hash"):
        raise CommandError("Archive and running image build identities do not match.")
    archived_oci = manifest.get("oci_digest") or ""
    current_oci = current_oci_digest or os.environ.get("SPACEWORKS_OCI_DIGEST", "")
    current_oci = current_oci.rsplit("@", 1)[-1]
    if archived_oci and current_oci and archived_oci != current_oci:
        raise CommandError("Archive and running OCI digests do not match.")
    if environment is None:
        check_setting_policies(manifest.get("settings", {}))
    else:
        check_setting_policies(manifest.get("settings", {}), environment=environment)
    for bucket in (settings.AWS_STORAGE_BUCKET_NAME, settings.PUBLIC_IMAGE_BUCKET):
        try:
            storage.client().head_bucket(Bucket=bucket)
        except Exception as exc:
            raise CommandError(
                f"Object-storage capability probe failed for bucket {bucket}."
            ) from exc
