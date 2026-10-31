"""Real plain tar/PAX bytes through the installed receiver, never tarfile mocks."""

import io
import tarfile

import pytest

from apps.backup.host_restore_files import extract_bundle, project_metadata
from apps.backup.host_restore_transport import RestoreHostError
from tests.backup.recovery_test_support import require_linux_root


def tar_bytes(path, entries=(), *, mode="w"):
    with tarfile.open(path, mode, format=tarfile.PAX_FORMAT) as archive:
        for name, raw in [("manifest.json", b"{}"), ("keys/env.json", b"{}"), *entries]:
            info = name if isinstance(name, tarfile.TarInfo) else tarfile.TarInfo(name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return path


def physical_header(name, size, kind=tarfile.REGTYPE):
    info = tarfile.TarInfo(name)
    info.size, info.type = size, kind
    return info.tobuf(format=tarfile.GNU_FORMAT)


def framed(key, value):
    payload = key + b"=" + value + b"\n"
    size = len(payload) + 2
    while len(str(size)) + 1 + len(payload) != size:
        size = len(str(size)) + 1 + len(payload)
    return str(size).encode() + b" " + payload


def pax_tar(path, raw, *, nested=False):
    data = physical_header("PaxHeader", len(raw), tarfile.XHDTYPE) + raw
    data += b"\0" * ((-len(raw)) % 512)
    if nested:
        data += physical_header("Nested", len(raw), tarfile.XHDTYPE) + raw + b"\0" * ((-len(raw)) % 512)
    data += physical_header("manifest.json", 2) + b"{}" + b"\0" * 510 + b"\0" * 1024
    path.write_bytes(data)
    return path


def test_genuine_producer_pax_and_sparse_looking_path_values_are_legal(tmp_path):
    require_linux_root()
    source = tmp_path / "producer"
    (source / "keys").mkdir(parents=True)
    (source / "manifest.json").write_bytes(b'{"valid":true}')
    (source / "keys/env.json").write_bytes(b"{}")
    name = "GNU.sparse-SCHILY.realsize-" + "x" * 130
    (source / name).write_bytes(b"ordinary long path payload")
    archive = tmp_path / "bundle.tar"
    with tarfile.open(archive, "w") as writer:
        writer.add(source, arcname=".")  # Actual archive_builder writer shape.
    project_metadata(archive, tmp_path / "metadata")
    assert not (tmp_path / "metadata" / name).exists()
    extract_bundle(archive, tmp_path / "bundle")
    assert (tmp_path / "bundle" / name).read_bytes() == b"ordinary long path payload"
    assert (tmp_path / "metadata/manifest.json").read_bytes() == b'{"valid":true}'


@pytest.mark.parametrize("raw", [
    b"x path=hello\n", b"99 path=hello\n", b"0 path=x\n", b"12 path=bad!", b"7 aaaa\n",
    framed(b"GNU.sparse.map", b"0,999"), framed(b"SCHILY.realsize", b"999"),
    framed(b"SCHILY.filetype", b"sparse"),
])
def test_malformed_or_sparse_pax_is_refused_before_metadata_write(tmp_path, raw):
    require_linux_root()
    archive = pax_tar(tmp_path / "bad.tar", raw)
    with pytest.raises(RestoreHostError):
        project_metadata(archive, tmp_path / "metadata")
    assert not (tmp_path / "metadata/manifest.json").exists()


def test_nested_and_global_pax_are_refused(tmp_path):
    require_linux_root()
    raw = framed(b"mtime", b"0")
    archive = pax_tar(tmp_path / "nested.tar", raw, nested=True)
    with pytest.raises(RestoreHostError):
        project_metadata(archive, tmp_path / "nested")
    archive.write_bytes(physical_header("global", 0, tarfile.XGLTYPE) + b"\0" * 1024)
    with pytest.raises(RestoreHostError):
        project_metadata(archive, tmp_path / "global")


def test_oversized_physical_pax_header_refuses_before_allocating_its_payload(tmp_path):
    require_linux_root()
    archive = tmp_path / "pax-cap.tar"
    size = 1024 * 1024 + 1
    with archive.open("wb") as stream:
        stream.write(physical_header("PaxHeader", size, tarfile.XHDTYPE))
        stream.seek(((size + 511) // 512) * 512, 1)
        stream.write(b"\0" * 1024)
    with pytest.raises(RestoreHostError, match="PAX header exceeds"):
        project_metadata(archive, tmp_path / "metadata")
    assert not (tmp_path / "metadata/manifest.json").exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE,
    tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.GNUTYPE_SPARSE])
def test_links_special_and_old_gnu_sparse_never_extract(tmp_path, kind):
    require_linux_root()
    archive = tmp_path / "special.tar"
    archive.write_bytes(physical_header("manifest.json", 0, kind) + b"\0" * 1024)
    with pytest.raises(RestoreHostError):
        extract_bundle(archive, tmp_path / "bundle")
    assert not (tmp_path / "bundle/manifest.json").exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../escape", "a//b", "manifest.json"])
def test_unsafe_or_duplicate_paths_are_refused(tmp_path, name):
    require_linux_root()
    archive = tar_bytes(tmp_path / "bad.tar", [(name, b"bad")])
    with pytest.raises(RestoreHostError):
        project_metadata(archive, tmp_path / "metadata")
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("order", ["file-first", "child-first", "directory-child-first"])
def test_file_and_ancestor_conflict_is_a_typed_screening_refusal(tmp_path, order):
    require_linux_root()
    parent = ("objects/private/a", b"parent file")
    child = ("objects/private/a/b", b"child file")
    if order == "directory-child-first":
        directory = tarfile.TarInfo("objects/private/a/b")
        directory.type = tarfile.DIRTYPE
        entries = [(directory, b""), parent]
    else:
        entries = [parent, child] if order == "file-first" else [child, parent]
    archive = tar_bytes(tmp_path / "conflict.tar", entries)
    with pytest.raises(RestoreHostError, match="conflicts with a directory path"):
        project_metadata(archive, tmp_path / "metadata")
    assert not (tmp_path / "metadata/objects").exists()
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("directory_first", [False, True])
def test_explicit_directory_and_implied_parent_remain_valid(tmp_path, directory_first):
    require_linux_root()
    directory = tarfile.TarInfo("objects/private")
    directory.type = tarfile.DIRTYPE
    entry = ("objects/private/a", b"ordinary payload")
    entries = [(directory, b""), entry] if directory_first else [entry, (directory, b"")]
    archive = tar_bytes(tmp_path / "directories.tar", entries)
    project_metadata(archive, tmp_path / "metadata")
    extract_bundle(archive, tmp_path / "bundle")
    assert (tmp_path / "bundle/objects/private/a").read_bytes() == b"ordinary payload"


@pytest.mark.parametrize("mode", ["w:gz", "w:bz2", "w:xz"])
def test_compressed_outer_tar_is_refused(tmp_path, mode):
    require_linux_root()
    archive = tar_bytes(tmp_path / "compressed.tar", mode=mode)
    with pytest.raises(RestoreHostError):
        project_metadata(archive, tmp_path / "metadata")


@pytest.mark.parametrize("size", [-1, 4096])
def test_negative_and_out_of_file_extents_fail_before_read(tmp_path, size):
    require_linux_root()
    archive = tmp_path / "extent.tar"
    archive.write_bytes(physical_header("manifest.json", size) + b"\0" * 512)
    with pytest.raises(RestoreHostError):
        project_metadata(archive, tmp_path / "metadata")


@pytest.mark.parametrize("name,cap", [("manifest.json", 64 * 1024 * 1024), ("keys/env.json", 1024 * 1024)])
@pytest.mark.parametrize("delta", [0, 1])
def test_real_serialized_metadata_boundary_with_sparse_disk_file(tmp_path, name, cap, delta):
    require_linux_root()
    archive = tmp_path / "cap.tar"
    other = "keys/env.json" if name == "manifest.json" else "manifest.json"
    # A sparse *filesystem* file saves allocation; this is an ordinary nonsparse tar member.
    with archive.open("wb") as stream:
        stream.write(physical_header(name, cap + delta))
        stream.seek(((cap + delta + 511) // 512) * 512, 1)
        stream.write(physical_header(other, 2) + b"{}" + b"\0" * 510 + b"\0" * 1024)
    if delta:
        with pytest.raises(RestoreHostError, match="byte limit"):
            project_metadata(archive, tmp_path / "metadata")
        assert not (tmp_path / "metadata" / name).exists()
    else:
        project_metadata(archive, tmp_path / "metadata")
        assert (tmp_path / "metadata" / name).stat().st_size == cap
