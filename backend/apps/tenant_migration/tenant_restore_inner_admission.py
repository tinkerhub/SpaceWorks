"""Validate authenticated inner structure without opening database or object storage."""

from types import SimpleNamespace

from .tenant_client_catalog import _digest, _is_sha256, validate_catalog_identity, validate_client_catalog
from .tenant_dump_envelope import TENANT_DEKS_MEMBER, _require_allowed_member
from .tenant_dump_manifest import verify_envelope_custody_manifest
from .tenant_restore_types import TenantRestoreRefused


def validate_authenticated_inner(inner, outer):
    try:
        source, lineage, contents = inner["source"], inner["lineage"], inner["contents"]
        compatibility = outer["compatibility"]
        if (inner["format"] != outer["format"] or inner["capture_id"] != outer["capture_id"]
                or type(source["encryption_mode"]) is not bool
                or type(source["makerspace_id"]) is not int or source["makerspace_id"] <= 0
                or source["postgres_major"] != outer["postgres_major"]
                or source["catalog_digest"] != compatibility["catalog_sha256"]
                or inner["source_pii_mode"] != compatibility["source_pii_mode"]
                or lineage["derivation_policy_sha256"] != compatibility["derivation_policy_sha256"]
                or not _is_sha256(lineage["database_image_sha256"])
                or not _is_sha256(lineage["object_ledger_sha256"])
                or not isinstance(contents, list)
                or len(contents) != compatibility["content_ledger_count"]
                or _digest(contents) != compatibility["content_ledger_sha256"]):
            raise ValueError
        paths = []
        object_members = {}
        for entry in contents:
            path = entry["path"]
            if not isinstance(path, str):
                raise ValueError
            _require_allowed_member(path, allow_inner_manifest=False)
            if entry == {"path": TENANT_DEKS_MEMBER, "present": False}:
                pass
            elif (set(entry) != {"path", "size", "sha256", "present"}
                  or entry["present"] is not True or type(entry["size"]) is not int
                  or entry["size"] < 0 or not _is_sha256(entry["sha256"])):
                raise ValueError
            if path.startswith("objects/"):
                object_members[path] = (entry["size"], entry["sha256"])
            paths.append(path)
        if paths != sorted(set(paths)) or "database.dump" not in paths:
            raise ValueError
        expected_objects = {}
        for item in inner["objects"]:
            if item.get("retention_state") == "expired":
                if item["member_path"] is not None or item["size"] != 0 or item["sha256"] != "":
                    raise ValueError
                continue
            member = item["member_path"]
            if member in expected_objects:
                raise ValueError
            expected_objects[member] = (item["size"], item["sha256"])
        if object_members != expected_objects:
            raise ValueError
        validate_catalog_identity(inner["capture_id"], source["deployment_identity"]["deployment_id"],
                                  source["makerspace_id"])
        catalog = validate_client_catalog(
            inner["api_client_catalog"], capture_id=inner["capture_id"],
            source_deployment_id=source["deployment_identity"]["deployment_id"],
            source_makerspace_id=source["makerspace_id"],
        )
        verify_envelope_custody_manifest(
            SimpleNamespace(pk=inner["capture_id"], source_encryption_mode=source["encryption_mode"],
                            source_makerspace_id=source["makerspace_id"],
                            source_deployment_identity=source["deployment_identity"]), inner, outer_version=2,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise TenantRestoreRefused("The authenticated Lane D inner manifest is invalid.") from exc
    return catalog
