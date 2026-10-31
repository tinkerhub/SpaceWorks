"""Read-only root delegation for old-environment signed-full admission."""

import hashlib
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType

from apps.backup.import_preflight import ImportPreflightError
from apps.backup.outer_manifest import manifest_digest


def prospective_environment(record_path, *, manifest, archive_sha256,
                            continuity_file, restore_id=None):
    """Only an exact root-sealed operation may compare prospective continuity."""
    try:
        path = Path(record_path)
        if path.parent != Path("/run/spaceworks-host") or path.name != (
            f"restore-prospective-{archive_sha256}.json"
        ):
            raise ValueError
        parent = path.parent.stat(follow_symlinks=False)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            facts = os.fstat(stream.fileno())
            if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
                    or parent.st_mode & 0o022 or not stat.S_ISREG(facts.st_mode)
                    or facts.st_uid != 0 or stat.S_IMODE(facts.st_mode) != 0o444
                    or facts.st_nlink != 1 or facts.st_size > 4096):
                raise ValueError
            record = json.load(stream)
        required = {"schema", "archive_sha256", "manifest_sha256", "continuity_sha256"}
        if not isinstance(record, dict) or set(record) != required | (
            {"restore_id"} if restore_id is not None else set()
        ):
            raise ValueError
        continuity_bytes = Path(continuity_file).read_bytes()
        if (record["schema"] != "spaceworks-restore-prospective-v1"
                or record["archive_sha256"] != archive_sha256
                or record["manifest_sha256"] != manifest_digest(manifest)
                or record["continuity_sha256"] != hashlib.sha256(continuity_bytes).hexdigest()
                or (restore_id is not None and record["restore_id"] != str(restore_id))):
            raise ValueError
        from apps.backup.import_preflight import _validate_continuity_secrets

        continuity = json.loads(continuity_bytes)
        _validate_continuity_secrets(continuity)
        environment = dict(os.environ)
        environment.update(continuity)
        return MappingProxyType(environment)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ImportPreflightError(
            "prospective_authority", "the exact root operation delegation is unavailable."
        ) from exc
