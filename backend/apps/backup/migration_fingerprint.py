"""Fingerprint installed migration packages without importing their source.

The boundary is every source/data file inside app/migrations, including helpers
that no numbered entrypoint currently imports, not external runtime libraries.
"""

from fnmatch import fnmatchcase
import hashlib
import os
from pathlib import Path
import stat


_NUMBERED_MIGRATION = "[0-9][0-9][0-9][0-9]_*.py"


def _assert_directory_chain(path):
    # Do not resolve(): doing so would hide symlinks in selected ancestry.
    for directory in (path, *path.parents):
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise OSError(f"migration ancestry is not a real directory: {directory}")


def _package_files(package):
    pending = [package]
    while pending:
        directory = pending.pop()
        _assert_directory_chain(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                path = Path(entry.path)
                # Classify before excluding caches: a cache-named symlink or
                # special file must refuse rather than silently disappear.
                if stat.S_ISDIR(info.st_mode):
                    if entry.name != "__pycache__":
                        pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    if path.suffix not in {".pyc", ".pyo"}:
                        yield path, info
                else:
                    raise OSError(f"migration input is not a regular file or directory: {path}")


def _inventory(root):
    _assert_directory_chain(root)
    files = []
    has_numbered_migration = False
    with os.scandir(root) as apps:
        for app in apps:
            app_info = app.stat(follow_symlinks=False)
            if not (stat.S_ISDIR(app_info.st_mode) or stat.S_ISLNK(app_info.st_mode)):
                continue
            package = Path(app.path) / "migrations"
            try:
                package.lstat()
            except (FileNotFoundError, NotADirectoryError):
                # An unrelated app symlink without migrations is outside this
                # inventory. A symlink supplying a package is rejected below.
                continue
            _assert_directory_chain(package)
            for path, info in _package_files(package):
                relative = path.relative_to(root).as_posix()
                files.append((relative, path, info))
                if path.parent == package and fnmatchcase(path.name, _NUMBERED_MIGRATION):
                    has_numbered_migration = True
    if not has_numbered_migration:
        raise OSError("no installed numbered migration files were found")
    return sorted(files, key=lambda item: item[0])


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _assert_same_file(info, expected, path):
    if not stat.S_ISREG(info.st_mode) or _file_identity(info) != _file_identity(expected):
        raise OSError(f"installed migration input changed while fingerprinting: {path}")


def _hash_file(digest, path, expected):
    _assert_directory_chain(path.parent)
    # NONBLOCK avoids hanging if a regular file becomes a FIFO before open;
    # NOFOLLOW rejects a last-component symlink even in that race window.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        _assert_same_file(os.fstat(descriptor), expected, path)
        digest.update(expected.st_size.to_bytes(8, "big"))
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
        if size != expected.st_size:
            raise OSError(f"installed migration input size changed while reading: {path}")
        _assert_same_file(os.fstat(descriptor), expected, path)
        _assert_directory_chain(path.parent)
        _assert_same_file(path.lstat(), expected, path)
    finally:
        os.close(descriptor)


def installed_migration_version(migrations_root):
    """Return the length-framed package digest; filesystem uncertainty is OSError."""
    root = Path(os.path.abspath(migrations_root))
    files = _inventory(root)
    digest = hashlib.sha256(b"spaceworks-django-migrations-v1\0")
    for relative, path, info in files:
        try:
            encoded_path = relative.encode("utf-8")
        except UnicodeError as exc:
            raise OSError("installed migration path is not UTF-8") from exc
        digest.update(len(encoded_path).to_bytes(8, "big") + encoded_path)
        _hash_file(digest, path, info)
    return f"django-migrations-v1:{digest.hexdigest()}"
