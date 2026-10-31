"""Exact full-payload verification for both tar members and extracted files."""

import hmac
from pathlib import Path
import tarfile

from apps.backup.digests import sha256_file
from apps.backup.errors import BackupBuildError
from apps.backup.full_manifest import verify_full_manifest
from apps.backup.full_manifest_validation import safe_path
from apps.backup.outer_manifest import _canonical_json


def _directories(paths):
    return {".", *(str(parent) for name in paths for parent in Path(name).parents)}


def verify_full_bundle(bundle, manifest, manifest_file, secrets_file):
    from apps.backup.import_preflight_bundle import (
        _decode_json, _member_sha256, _read_member_json, read_json_file,
    )

    verify_full_manifest(manifest)
    declared = {item["path"]: item for item in manifest["contents"]}
    allowed_files = {"manifest.json", *declared}
    directories = _directories(allowed_files)
    try:
        with tarfile.open(bundle, mode="r:*") as archive:
            seen, files = set(), {}
            for member in archive.getmembers():
                name = member.name[2:] if member.name.startswith("./") else member.name
                if name != ".":
                    safe_path(name)
                if name in seen:
                    raise ValueError
                seen.add(name)
                if member.isdir():
                    if name not in directories:
                        raise ValueError
                elif member.isfile() and name in allowed_files:
                    files[name] = member
                else:
                    raise ValueError
            if set(files) != allowed_files:
                raise ValueError
            embedded = _read_member_json(archive, files["manifest.json"], "manifest")
            if _canonical_json(embedded) != _canonical_json(manifest):
                raise ValueError
            if _canonical_json(read_json_file(manifest_file, "manifest")) != _canonical_json(manifest):
                raise ValueError
            for name, fact in declared.items():
                if files[name].size != fact["size"] or not hmac.compare_digest(
                    _member_sha256(archive, files[name]), fact["sha256"]
                ):
                    raise ValueError
            # Compare actual continuity bytes as well as the unique-key JSON values.
            raw = Path(secrets_file).read_bytes()
            fact = declared["keys/env.json"]
            if len(raw) != fact["size"] or sha256_file(secrets_file) != fact["sha256"]:
                raise ValueError
            _decode_json(raw, "continuity-secret")
    except (OSError, tarfile.TarError, ValueError, TypeError) as exc:
        raise BackupBuildError("The signed full bundle members differ from the complete ledger.") from exc


def verify_full_root(root, manifest):
    from apps.backup.import_preflight_bundle import read_json_file

    verify_full_manifest(manifest)
    root = Path(root)
    declared = {item["path"]: item for item in manifest["contents"]}
    allowed_files = {"manifest.json", *declared}
    directories = _directories(allowed_files)
    try:
        if root.is_symlink() or not root.is_dir():
            raise ValueError
        actual = set()
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValueError
            if path.is_dir():
                if name not in directories:
                    raise ValueError
            elif path.is_file() and name in allowed_files:
                if path.stat().st_nlink != 1:
                    raise ValueError
                actual.add(name)
            else:
                raise ValueError
        if actual != allowed_files:
            raise ValueError
        if _canonical_json(read_json_file(root / "manifest.json", "manifest")) != _canonical_json(manifest):
            raise ValueError
        for name, fact in declared.items():
            path = root / name
            if path.stat().st_size != fact["size"] or sha256_file(path) != fact["sha256"]:
                raise ValueError
    except (OSError, ValueError, TypeError) as exc:
        raise BackupBuildError("The extracted signed full payload differs from its complete ledger.") from exc
