"""Target compatibility using read-only prospective or installed settings."""

import os
from types import MappingProxyType

from django.conf import settings
from django.core.management.base import CommandError

from apps.backup import storage
from apps.backup.import_preflight import ImportPreflightError
from apps.backup.management.commands.backup_preflight import check_setting_policies


def validate_full_target(manifest, continuity, *, environment=None):
    # The signature has already used the configured, out-of-band host trust key.
    environment = MappingProxyType(dict(os.environ)) if environment is None else environment
    if environment.get("SPACEWORKS_OCI_DIGEST", "") != manifest["oci_digest"]:
        raise ImportPreflightError("oci_identity", "archive and target OCI identities differ or are missing.")
    try:
        check_setting_policies(manifest["settings"], environment=environment)
    except CommandError as exc:
        raise ImportPreflightError("settings_policy", str(exc)) from exc
    for bucket in (settings.AWS_STORAGE_BUCKET_NAME, settings.PUBLIC_IMAGE_BUCKET):
        try:
            storage.client().head_bucket(Bucket=bucket)
        except Exception as exc:
            raise ImportPreflightError(
                "storage_capability", "the target object-storage capability probe failed."
            ) from exc
