"""Private shared scan progress; a cursor never grants deletion authority."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat

from django.conf import settings

from apps.backup import host_private_file
from apps.backup.host_marker import MarkerError
from apps.backup.object_restore_versions import ObjectRestoreError


CURSOR_NAME = "rollback-cleanup-progress.json"
MAX_CURSOR_BYTES = 256
MAX_LAST_ID = 9223372036854775807


class RollbackCleanupProgressUnavailable(ObjectRestoreError):
    def __init__(self):
        super().__init__("Rollback cleanup progress is unavailable or untrusted.")


@dataclass(frozen=True)
class RollbackCleanupProgress:
    path: Path
    last_id: int
    directory_identity: tuple
    file_identity: tuple | None


def _directory_identity(info):
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise RollbackCleanupProgressUnavailable()
    return info.st_dev, info.st_ino


def _file_identity(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or info.st_mode & 0o077
            or not 0 <= info.st_size <= MAX_CURSOR_BYTES):
        raise RollbackCleanupProgressUnavailable()
    return (info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise RollbackCleanupProgressUnavailable()
        result[name] = value
    return result


def _validate_last_id(last_id):
    if type(last_id) is not int or not 0 <= last_id <= MAX_LAST_ID:
        raise RollbackCleanupProgressUnavailable()
    return last_id


def _parse(raw):
    if len(raw) > MAX_CURSOR_BYTES:
        raise RollbackCleanupProgressUnavailable()
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if (not isinstance(payload, dict) or set(payload) != {"version", "last_id"}
            or type(payload["version"]) is not int or payload["version"] != 1):
        raise RollbackCleanupProgressUnavailable()
    return _validate_last_id(payload["last_id"])


def _read_progress(path):
    # Keep canonical parent aliases (e.g. /var); never resolve a final symlink.
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    expected_directory = _directory_identity(directory.stat(follow_symlinks=False))
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if _directory_identity(os.fstat(directory_fd)) != expected_directory:
            raise RollbackCleanupProgressUnavailable()
        identity, last_id = None, 0
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(fd, "rb") as handle:
                identity = _file_identity(os.fstat(handle.fileno()))
                last_id = _parse(handle.read(MAX_CURSOR_BYTES + 1))
                if _file_identity(os.fstat(handle.fileno())) != identity:
                    raise RollbackCleanupProgressUnavailable()
            linked = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
            if _file_identity(linked) != identity:
                raise RollbackCleanupProgressUnavailable()
        if _directory_identity(directory.stat(follow_symlinks=False)) != expected_directory:
            raise RollbackCleanupProgressUnavailable()
        return RollbackCleanupProgress(path, last_id, expected_directory, identity)
    finally:
        os.close(directory_fd)


def read_cleanup_progress():
    """Call only under the deployment lock and outer unscoped boundary."""
    try:
        # Use the configured shared work mount directly, with either path layout.
        return _read_progress(Path(settings.BACKUP_OPS_DIR) / CURSOR_NAME)
    except (OSError, ValueError, TypeError) as exc:
        raise RollbackCleanupProgressUnavailable() from exc


def write_cleanup_progress(progress, last_id):
    """Revalidate trust before the existing atomic, file-and-directory fsync writer."""
    try:
        _validate_last_id(last_id)
        if _read_progress(progress.path) != progress:
            raise RollbackCleanupProgressUnavailable()
        payload = json.dumps({"version": 1, "last_id": last_id}, separators=(",", ":"))
        host_private_file.write_private_file_fsynced(
            progress.path, payload, mode=0o600, require_root_owned=False,
        )
        # The shared writer's non-root mode does not enforce owner/link count.
        confirmed = _read_progress(progress.path)
        if confirmed.directory_identity != progress.directory_identity or confirmed.last_id != last_id:
            raise RollbackCleanupProgressUnavailable()
    except (OSError, ValueError, TypeError, MarkerError) as exc:
        raise RollbackCleanupProgressUnavailable() from exc
