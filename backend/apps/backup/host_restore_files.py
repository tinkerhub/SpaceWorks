"""Seal app-produced bytes into root authority and read-only app delegations."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile

from .full_format import CONTINUITY_MAX_BYTES, MANIFEST_MAX_BYTES
from .host_private_file import _fsync_directory, write_private_file_fsynced
from .host_restore_transport import RestoreHostError, trusted


BLOCK = 1024 * 1024


def _screen_pax(raw):
    offset = 0
    while offset < len(raw):
        delimiter = raw.find(b" ", offset)
        length = raw[offset:delimiter] if delimiter >= 0 else b""
        if not length.isdigit() or len(length) > 7:
            raise RestoreHostError("An archive PAX record has an invalid length.")
        end = offset + int(length)
        if end <= delimiter + 2 or end > len(raw) or raw[end - 1:end] != b"\n":
            raise RestoreHostError("An archive PAX record is truncated or malformed.")
        key, separator, value = raw[delimiter + 1:end - 1].partition(b"=")
        if not key or not separator:
            raise RestoreHostError("An archive PAX record lacks its key and value.")
        if (key.startswith(b"GNU.sparse") or key == b"SCHILY.realsize"
                or (key == b"SCHILY.filetype" and value == b"sparse")):
            raise RestoreHostError("Sparse archive members are unsupported.")
        offset = end


def seal_file(source, target, *, mode=0o600):
    source, target = Path(source), Path(target)
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    trusted(target.parent, directory=True)
    temporary = target.with_name("." + target.name + ".sealing")
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "rb") as reader:
            before = os.fstat(reader.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise RestoreHostError("An app-produced input is not a unique regular file.")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, mode)
            with os.fdopen(fd, "wb") as writer:
                while chunk := reader.read(BLOCK):
                    writer.write(chunk)
                    digest.update(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            after = os.fstat(reader.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise RestoreHostError("An app-produced input changed while being sealed.")
        os.replace(temporary, target)
        os.chmod(target, mode)
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return digest.hexdigest()


def delegate_file(source, target, *, public=False):
    target = Path(target)
    seal_file(source, target, mode=0o444 if public else 0o440)
    if not public:
        os.chown(target, 0, 10001)
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    _fsync_directory(target.parent)
    return target


def delegate_tree(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(mode=0o750)
    os.chown(target, 0, 10001)
    for item in source.iterdir():
        if item.is_dir() and not item.is_symlink():
            delegate_tree(item, target / item.name)
        elif item.is_file() and not item.is_symlink():
            delegate_file(item, target / item.name)
        else:
            raise RestoreHostError("A sealed bundle contains an unsupported filesystem object.")
    _fsync_directory(target)
    _fsync_directory(target.parent)


class _PlainTarInfo(tarfile.TarInfo):
    def _proc_member(self, archive):
        # Check physical headers before tarfile reads PAX or seeks over payload.
        end = archive.fileobj.tell() + ((self.size + 511) // 512) * 512
        if self.size < 0 or end > os.fstat(archive.fileobj.fileno()).st_size:
            raise RestoreHostError("An archive member extends beyond the sealed plain tar.")
        if self.type == tarfile.XHDTYPE:
            # The shipped PAX writer needs timestamps and long paths, never sparse
            # maps. Bound extension parsing too, before tarfile allocates its bytes.
            if self.size > CONTINUITY_MAX_BYTES or getattr(archive, "_host_pax_active", False):
                raise RestoreHostError("An archive PAX header exceeds the fixed metadata limit.")
            position = archive.fileobj.tell()
            raw = archive.fileobj.read(self.size)
            archive.fileobj.seek(position)
            _screen_pax(raw)
        elif self.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE}:
            raise RestoreHostError("Links, sparse and special archive members are forbidden.")
        if self.type != tarfile.XHDTYPE:
            return super()._proc_member(archive)
        archive._host_pax_active = True
        try:
            return super()._proc_member(archive)
        finally:
            archive._host_pax_active = False


def _plain_members(archive):
    seen = set()
    regular_paths, implied_parents = set(), set()
    try:
        with tarfile.open(archive, mode="r:", tarinfo=_PlainTarInfo) as bundle:
            length = os.fstat(bundle.fileobj.fileno()).st_size
            for member in bundle:
                name = member.name.removeprefix("./")
                if member.name in {".", "./"} and member.isdir():
                    name = "."
                path = PurePosixPath(name)
                if (not name or "\x00" in name or path.is_absolute() or ".." in path.parts
                        or path.as_posix() != name or name in seen or (name == "." and not member.isdir())):
                    raise RestoreHostError("The archive member path is unsafe or repeated.")
                parents = {parent.as_posix() for parent in path.parents}
                if parents & regular_paths or (member.isfile() and name in implied_parents):
                    raise RestoreHostError("An archive regular file conflicts with a directory path.")
                seen.add(name)
                implied_parents.update(parents)
                if member.isfile():
                    regular_paths.add(name)
                if (member.sparse is not None or member.size < 0
                        or member.offset_data + ((member.size + 511) // 512) * 512 > length
                        or member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE}
                        or (member.isdir() and member.size != 0)):
                    raise RestoreHostError("The sealed plain tar has an unsupported member extent or type.")
                yield bundle, member, name
    except (OSError, tarfile.TarError, ValueError) as exc:
        raise RestoreHostError("The sealed archive is not a supported plain tar.") from exc


def project_metadata(archive, destination):
    """Screen the whole plain tar; write only two bounded private metadata files."""
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    limits = {"manifest.json": MANIFEST_MAX_BYTES, "keys/env.json": CONTINUITY_MAX_BYTES}
    found = set()
    for bundle, member, name in _plain_members(archive):
        if name not in limits:
            continue
        cap = limits[name]
        if not member.isfile() or member.size > cap:
            raise RestoreHostError("Archive metadata exceeds the fixed serialized byte limit.")
        source = bundle.extractfile(member)
        if source is None:
            raise RestoreHostError("Archive metadata cannot be read.")
        with source:
            raw = source.read(cap + 1)
        if len(raw) != member.size or len(raw) > cap:
            raise RestoreHostError("Archive metadata is truncated or exceeds its byte limit.")
        write_private_file_fsynced(destination / name, raw)
        found.add(name)
    if found != set(limits):
        raise RestoreHostError("The archive lacks required bounded metadata.")


def extract_bundle(archive, destination):
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    for bundle, member, name in _plain_members(archive):
        if member.isdir():
            (destination / name).mkdir(mode=0o700, parents=True, exist_ok=True)
            continue
        target = destination / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        source = bundle.extractfile(member)
        if source is None:
            raise RestoreHostError("An archive member cannot be read.")
        with source, target.open("xb") as stream:
            os.chmod(target, 0o600)
            shutil.copyfileobj(source, stream, BLOCK)
            stream.flush()
            os.fsync(stream.fileno())
    for directory in sorted((p for p in destination.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        _fsync_directory(directory)
    _fsync_directory(destination)
    _fsync_directory(destination.parent)


def public_json(path, payload):
    path = Path(path)
    temporary = path.with_name("." + path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o444)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def install_environment(path, contents):
    path = trusted(path, private=True)
    trusted(path.parent, directory=True)
    temporary = path.with_name("." + path.name + ".restore-new")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
