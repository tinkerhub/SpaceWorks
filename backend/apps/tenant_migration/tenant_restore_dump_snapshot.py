"""Bind authenticated v2 dump bytes to a private, invocation-owned restore file."""

from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import stat

from .tenant_restore_artifact_files import file_identity, open_artifact_file
from .tenant_restore_types import TenantRestoreRefused

CHUNK_BYTES = 1024 * 1024
DUMP_NAME = "database.dump"


def _inode(info):
    return info.st_dev, info.st_ino


def _identity(info):
    return (*_inode(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory(info, *, private):
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & (0o077 if private else 0o022)):
        raise ValueError("The database snapshot directory is unsafe.")


def _open_safe_parent(path):
    # Canonicalize system aliases (e.g. /var), then pin every component without
    # following symlinks. Other users must not be able to swap a path ancestor.
    try:
        path = path.resolve(strict=True)
    except RuntimeError as exc:
        raise ValueError("The database snapshot parent cannot be resolved.") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            parent = os.fstat(fd)
            root_sticky = parent.st_uid == 0 and parent.st_mode & stat.S_ISVTX
            if (parent.st_uid not in (0, os.geteuid())
                    or (parent.st_mode & 0o022 and not root_sticky)):
                raise ValueError("The database snapshot ancestor is unsafe.")
            child_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child_fd
        _directory(os.fstat(fd), private=False)
        return path, fd
    except BaseException:
        os.close(fd)
        raise


class _DumpSnapshot:
    def __init__(self, ops_dir, expected_digest):
        self.root = Path(ops_dir)
        if not self.root.is_absolute() or ".." in self.root.parts:
            raise ValueError("The database snapshot parent must be absolute.")
        self.expected_digest = expected_digest
        self.name = ".tenant-restore-dump-" + secrets.token_hex(16)
        self.root_fd = self.dir_fd = self.file_fd = None
        self.root_inode = self.dir_inode = self.file_inode = None
        self.baseline = None

    def create(self):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        self.root, self.root_fd = _open_safe_parent(self.root)
        root = os.fstat(self.root_fd)
        _directory(root, private=False)
        self.root_inode = _inode(root)
        os.mkdir(self.name, mode=0o700, dir_fd=self.root_fd)
        created = os.stat(self.name, dir_fd=self.root_fd, follow_symlinks=False)
        self.dir_inode = _inode(created)
        _directory(created, private=True)
        self.dir_fd = os.open(self.name, flags, dir_fd=self.root_fd)
        if _inode(os.fstat(self.dir_fd)) != self.dir_inode:
            raise ValueError("The database snapshot directory changed.")
        os.fchmod(self.dir_fd, 0o700)
        self.file_fd = os.open(
            DUMP_NAME, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=self.dir_fd,
        )
        self.file_inode = _inode(os.fstat(self.file_fd))
        os.fchmod(self.file_fd, 0o600)

    def copy(self, source_path):
        # One private nofollow source descriptor; never hash then reopen the source.
        with open_artifact_file(source_path, private=True) as source:
            before = file_identity(source)
            if before[2] <= 0:
                raise ValueError("The database dump is empty.")
            remaining = before[2]
            while remaining:
                chunk = source.read(min(CHUNK_BYTES, remaining))
                if not chunk:
                    raise ValueError("The database dump changed during copying.")
                remaining -= len(chunk)
                pending = memoryview(chunk)
                while pending:
                    written = os.write(self.file_fd, pending)
                    if written <= 0:
                        raise OSError("The database snapshot write did not progress.")
                    pending = pending[written:]
            if source.read(1) or file_identity(source) != before:
                raise ValueError("The database dump changed during copying.")
        os.fsync(self.file_fd)
        os.fsync(self.dir_fd)
        os.fsync(self.root_fd)
        self.baseline = _identity(os.fstat(self.file_fd))
        self.verified_path()

    def _check_locations(self):
        root = os.stat(self.root, follow_symlinks=False)
        directory = os.stat(self.name, dir_fd=self.root_fd, follow_symlinks=False)
        _directory(root, private=False)
        _directory(directory, private=True)
        if (_inode(root) != self.root_inode or _inode(directory) != self.dir_inode
                or _inode(os.fstat(self.dir_fd)) != self.dir_inode):
            raise ValueError("The database snapshot directory changed.")
        opened = os.fstat(self.file_fd)
        named = os.stat(DUMP_NAME, dir_fd=self.dir_fd, follow_symlinks=False)
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode)
                or opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_nlink != 1 or _identity(opened) != self.baseline
                or _identity(named) != self.baseline):
            raise ValueError("The database snapshot file changed.")

    def verified_path(self):
        """Rehash the pinned copy and check its pathname immediately before restore."""
        try:
            self._check_locations()
            os.lseek(self.file_fd, 0, os.SEEK_SET)
            digest = hashlib.sha256()
            remaining = self.baseline[2]
            if remaining <= 0:
                raise ValueError("The database snapshot is empty.")
            while remaining:
                chunk = os.read(self.file_fd, min(CHUNK_BYTES, remaining))
                if not chunk:
                    raise ValueError("The database snapshot was truncated.")
                digest.update(chunk)
                remaining -= len(chunk)
            if os.read(self.file_fd, 1) or not hmac.compare_digest(
                digest.hexdigest(), self.expected_digest,
            ):
                raise ValueError("The database snapshot differs from its authenticated proof.")
            self._check_locations()
            return str(self.root / self.name / DUMP_NAME)
        except (OSError, ValueError, TypeError) as exc:
            raise TenantRestoreRefused("Authenticated database snapshot validation failed.") from exc

    def cleanup(self):
        # Never recurse or follow a replacement. The pinned directory, not its
        # current pathname, owns the unlink; a foreign file at DUMP_NAME survives.
        try:
            if self.dir_fd is not None and self.file_inode is not None:
                try:
                    named = os.stat(DUMP_NAME, dir_fd=self.dir_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    if stat.S_ISREG(named.st_mode) and _inode(named) == self.file_inode:
                        os.unlink(DUMP_NAME, dir_fd=self.dir_fd)
                        os.fsync(self.dir_fd)
        finally:
            try:
                if self.root_fd is not None and self.dir_inode is not None:
                    try:
                        named = os.stat(self.name, dir_fd=self.root_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        if stat.S_ISDIR(named.st_mode) and _inode(named) == self.dir_inode:
                            os.rmdir(self.name, dir_fd=self.root_fd)
                            os.fsync(self.root_fd)
            finally:
                for fd in (self.file_fd, self.dir_fd, self.root_fd):
                    if fd is not None:
                        os.close(fd)


@contextmanager
def verified_database_dump(ops_dir, artifact, context):
    """Yield a late path check; only actual v1 keeps the legacy adapter contract."""
    if context.outer_version == 1:
        yield lambda: artifact.database_dump_path()
        return
    snapshot = None
    active_error = None
    try:
        try:
            digest = context.database_member_sha256
            if (context.outer_version != 2 or not isinstance(digest, str) or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)):
                raise ValueError("An authenticated database member digest is required.")
            snapshot = _DumpSnapshot(ops_dir, digest)
            snapshot.create()
            snapshot.copy(artifact.database_dump_path())
        except (OSError, ValueError, TypeError, AttributeError, NotImplementedError) as exc:
            raise TenantRestoreRefused("Authenticated database snapshot preparation failed.") from exc
        yield snapshot.verified_path
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        if snapshot is not None:
            try:
                snapshot.cleanup()
            except OSError as exc:
                if active_error is None:
                    raise TenantRestoreRefused("Private database snapshot cleanup failed.") from exc
                active_error.add_note("Private database snapshot cleanup failed.")
