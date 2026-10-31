"""Closed schema for full custody; B1 proof/reservation claims are forbidden."""

from datetime import datetime
import json
from pathlib import PurePosixPath
import re
import uuid

from apps.backup.errors import BackupBuildError
from apps.backup.full_format import FULL_FORMAT, FULL_PROTOCOL
from apps.backup.full_source_identity import validate_source_identity
from apps.backup.main_projection_registry import OMITTED_OPERATIONAL_MODELS
from apps.backup.outer_manifest_facts import closure_digest_from_slice_ledgers, digest_json
from apps.backup.outer_manifest_validation import component_id
from apps.backup.settings_policy import POLICIES, Policy


_FIELDS = frozenset("""
format protocol_version artifact_id capture_id source_capture source_timestamp
custody_mode build_identity makerspace_sets main_component slice_components
user_closure_digest archive_id backup_run_id scope age_encrypted snapshot_at
build oci_digest covered_makerspace_ids excluded_makerspace_ids partial
recipient_fingerprints slices contents settings storage postgres makerspace_id purge_warning
omitted_operational_models
""".split())
_DIGEST = re.compile(r"[0-9a-f]{64}")


def digest(value):
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise ValueError
    return value


def equal_json(actual, expected):
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
        expected, sort_keys=True, allow_nan=False
    )


def validate_full_manifest(manifest):
    try:
        _validate(manifest)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise BackupBuildError("The signed full archive schema is invalid.") from exc


def _validate(m):
    if not isinstance(m, dict) or set(m) != _FIELDS:
        raise ValueError
    if (
        m["format"] != FULL_FORMAT or m["protocol_version"] != FULL_PROTOCOL
        or m["custody_mode"] != "full-platform-readable"
        or m["scope"] != "deployment" or m["makerspace_id"] is not None
        or m["age_encrypted"] is not True or m["partial"] is not False
        or m["excluded_makerspace_ids"] != [] or m["slices"] != []
        or m["slice_components"] != []
        or m["user_closure_digest"] != closure_digest_from_slice_ledgers(())
        or not isinstance(m["purge_warning"], str)
        or m["omitted_operational_models"] != sorted(OMITTED_OPERATIONAL_MODELS)
    ):
        raise ValueError
    for name in ("artifact_id", "archive_id", "capture_id"):
        if str(uuid.UUID(m[name])) != m[name]:
            raise ValueError
    if m["backup_run_id"] is not None and str(uuid.UUID(m["backup_run_id"])) != m["backup_run_id"]:
        raise ValueError
    stamp = datetime.fromisoformat(m["snapshot_at"])
    if stamp.tzinfo is None or m["source_timestamp"] != m["snapshot_at"]:
        raise ValueError
    ids = m["covered_makerspace_ids"]
    if (
        not isinstance(ids, list) or any(type(pk) is not int or pk <= 0 for pk in ids)
        or ids != sorted(set(ids)) or m["archive_id"] != m["artifact_id"]
        or not equal_json(m["makerspace_sets"], {"retained": ids, "readable_main": ids, "sovereign": []})
    ):
        raise ValueError
    fingerprints = m["recipient_fingerprints"]
    if (
        not isinstance(fingerprints, list) or not fingerprints
        or any(not digest(value) for value in fingerprints)
        or fingerprints != sorted(set(fingerprints))
    ):
        raise ValueError
    build = m["build"]
    if (
        not isinstance(build, dict) or set(build) != {"source_hash", "git_sha", "git_describe", "built_at"}
        or any(not isinstance(value, str) or not value for value in build.values())
        or not digest(build["source_hash"]) or not isinstance(m["oci_digest"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", m["oci_digest"]) is None
        or not equal_json(m["build_identity"], {"build": build, "oci_digest": m["oci_digest"]})
    ):
        raise ValueError
    pg = m["postgres"]
    if (
        not isinstance(pg, dict)
        or set(pg) != {"source_server_major", "client", "supported_source_majors"}
        or type(pg["source_server_major"]) is not int
        or pg["source_server_major"] not in {14, 15, 16, 17}
        or not equal_json(pg["supported_source_majors"], [14, 15, 16, 17])
        or not isinstance(pg["client"], str)
        or re.search(r"PostgreSQL\)\s+" + str(pg["source_server_major"]) + r"(?:\.|\s|$)", pg["client"]) is None
    ):
        raise ValueError
    source = m["source_capture"]
    if (
        not isinstance(source, dict) or set(source) != {
            "capture_id", "database_identity", "server_identity", "dump_sha256", "object_ownership_digest"
        } or source["capture_id"] != m["capture_id"]
        or not isinstance(source["database_identity"], str) or not source["database_identity"]
        or not digest(source["dump_sha256"]) or not digest(source["object_ownership_digest"])
    ):
        raise ValueError
    validate_source_identity(source["database_identity"], source["server_identity"], pg["source_server_major"])
    contents = _contents(m["contents"])
    if "database.dump" not in contents or "keys/env.json" not in contents:
        raise ValueError
    dump = contents["database.dump"]
    if dump["size"] <= 0 or dump["sha256"] != source["dump_sha256"]:
        raise ValueError
    if not equal_json(m["main_component"], {
        "component_id": component_id(m["capture_id"], "main"), "kind": "main",
        "path": "database.dump", "size_bytes": dump["size"],
        "ciphertext_sha256": dump["sha256"], "recipient_fingerprints": fingerprints,
        "semantic_digest": digest_json({"format": FULL_FORMAT, "source_capture": source}),
    }):
        raise ValueError
    _settings(m["settings"])
    _storage(m["storage"], contents)


def _contents(entries):
    if not isinstance(entries, list) or not entries:
        raise ValueError
    result = {}
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise ValueError
        name = safe_path(item["path"])
        if (
            name in result or name == "manifest.json"
            or not (name in {"database.dump", "keys/env.json"} or name.startswith("objects/"))
            or type(item["size"]) is not int or item["size"] < 0 or not digest(item["sha256"])
        ):
            raise ValueError
        result[name] = item
    if list(result) != sorted(result):
        raise ValueError
    return result


def _settings(settings):
    if not isinstance(settings, dict) or set(settings) != {name for name, policy in POLICIES.items() if policy.policy != Policy.EXCLUDED}:
        raise ValueError
    for name, policy in POLICIES.items():
        if policy.policy == Policy.EXCLUDED:
            continue
        fact = settings[name]
        expected = (
            {"policy", "fingerprint"} if policy.policy == Policy.EXACT_FINGERPRINT else
            {"policy", "configured"} if policy.policy == Policy.CAPABILITY_PROBE else
            {"policy", "value"}
        )
        expected = expected | {"blocks_restore"}
        if (
            not isinstance(fact, dict) or set(fact) != expected
            or fact["policy"] != policy.policy or fact["blocks_restore"] is not policy.blocks_restore
        ):
            raise ValueError
        if "fingerprint" in fact and not digest(fact["fingerprint"]):
            raise ValueError
        if "configured" in fact and type(fact["configured"]) is not bool:
            raise ValueError
        if "value" in fact and not isinstance(fact["value"], str):
            raise ValueError


def _storage(storage, contents):
    if not isinstance(storage, dict) or set(storage) != {"consistency", "objects"}:
        raise ValueError
    modes = storage["consistency"]
    if not isinstance(modes, dict) or set(modes) != {"private", "public_image"} or any(
        mode not in {"versioned", "quiesced"} for mode in modes.values()
    ):
        raise ValueError
    if not isinstance(storage["objects"], list):
        raise ValueError
    seen, live = set(), set()
    fields = {"bucket_kind", "canonical_component", "makerspace_id", "module_key", "key",
              "version_id", "size", "sha256", "metadata", "content_type", "headers"}
    for item in storage["objects"]:
        expired = item.get("retention_state") == "expired"
        allowed = fields | ({"retention_state", "object_expired_at", "expired_size_bytes"} if expired else set())
        if set(item) != allowed or item["bucket_kind"] not in modes or item["canonical_component"] != "main":
            raise ValueError
        key = safe_path(item["key"])
        path = f"objects/{item['bucket_kind']}/{key}"
        if path in seen or type(item["size"]) is not int or item["size"] < 0:
            raise ValueError
        seen.add(path)
        if expired:
            if item["size"] != 0 or item["sha256"] != "" or path in contents:
                raise ValueError
            if datetime.fromisoformat(item["object_expired_at"]).tzinfo is None:
                raise ValueError
            if item["expired_size_bytes"] is not None and (
                type(item["expired_size_bytes"]) is not int or item["expired_size_bytes"] < 0
            ):
                raise ValueError
        else:
            if contents.get(path) != {"path": path, "size": item["size"], "sha256": item["sha256"]}:
                raise ValueError
            live.add(path)
        if (
            (item["makerspace_id"] is not None and (type(item["makerspace_id"]) is not int or item["makerspace_id"] <= 0))
            or not isinstance(item["module_key"], str) or not isinstance(item["metadata"], dict)
            or not isinstance(item["headers"], dict) or not isinstance(item["content_type"], str)
            or (item["version_id"] is not None and not isinstance(item["version_id"], str))
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in item["metadata"].items())
            or set(item["headers"]) - {
                "CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage",
                "ContentType", "Expires", "WebsiteRedirectLocation",
            }
            or any(not isinstance(value, str) for value in item["headers"].values())
        ):
            raise ValueError
    if set(contents) != {"database.dump", "keys/env.json"} | live:
        raise ValueError
