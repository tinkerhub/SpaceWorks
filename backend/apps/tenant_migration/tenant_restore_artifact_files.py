"""Pinned regular-file reads for private host operation artifacts."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat

MAX_INNER_MANIFEST_BYTES = 32 * 1024 * 1024


def file_identity(handle):
    info = os.fstat(handle.fileno())
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def open_artifact_file(path, *, private=False):
    path = Path(path)
    if private and not path.is_absolute():
        raise ValueError("Operation artifact paths must be absolute.")
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    fd = None
    try:
        parent = os.fstat(parent_fd)
        if private and (parent.st_uid != os.geteuid() or parent.st_mode & 0o077):
            raise ValueError("Operation artifact directory must be private and owned.")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Operation artifacts must be regular files.")
        if private and (info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError("Operation artifacts must be private and owned.")
        with os.fdopen(fd, "rb") as handle:
            fd = None
            yield handle
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)


def read_inner_manifest_bytes(path):
    with open_artifact_file(path, private=True) as handle:
        before = file_identity(handle)
        if not 0 < before[2] <= MAX_INNER_MANIFEST_BYTES:
            raise ValueError("The inner manifest exceeds the supported size.")
        data = handle.read(MAX_INNER_MANIFEST_BYTES + 1)
        if len(data) != before[2] or file_identity(handle) != before:
            raise ValueError("The inner manifest changed during inspection.")
        return data
