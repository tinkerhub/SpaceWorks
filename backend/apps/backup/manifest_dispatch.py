"""Explicit format dispatch; registered identity owns restore routing."""

from apps.backup.digests import SUPPORTED_ARCHIVE_FORMATS
from apps.backup.errors import BackupBuildError
from apps.backup.full_format import FULL_FORMAT
from apps.backup.outer_manifest import _canonical_json, verify_outer_manifest


def manifest_kind(manifest):
    if not isinstance(manifest, dict):
        raise BackupBuildError("The archive manifest is not an object.")
    if manifest.get("format") == FULL_FORMAT:
        return "full"
    protocol = manifest.get("protocol_version")
    if (
        isinstance(protocol, str) and protocol.startswith("spaceworks-lane-e-b1-")
    ) or manifest.get("format") == "spaceworks-lane-e-e3-compound-v1":
        return "compound"
    if (
        manifest.get("format") in SUPPORTED_ARCHIVE_FORMATS
        and "protocol_version" not in manifest
        and "archive_signature" not in manifest
        and "source_partition_proof" not in manifest
        and "main_component" not in manifest
        and "slice_components" not in manifest
        and manifest.get("partial", False) is False
    ):
        return "legacy"
    raise BackupBuildError("Restore refused [format_unsupported]: unknown archive format.")


def verify_signed_manifest(manifest):
    kind = manifest_kind(manifest)
    if kind == "full":
        from apps.backup.full_manifest import verify_full_manifest

        return verify_full_manifest(manifest)
    if kind == "compound":
        return verify_outer_manifest(manifest)
    raise BackupBuildError("An unsigned archive cannot enter signed admission.")


def registered_manifest_kind(registered, extracted):
    kind = manifest_kind(registered)
    if kind != "legacy":
        if _canonical_json(registered) != _canonical_json(extracted):
            raise BackupBuildError("The extracted manifest differs from registered signed identity.")
        verify_signed_manifest(registered)
    elif manifest_kind(extracted) != "legacy":
        raise BackupBuildError("The extracted manifest changed registered legacy routing.")
    return kind
