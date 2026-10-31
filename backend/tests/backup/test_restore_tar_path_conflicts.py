"""Real plain-tar path conflicts must fail during bounded metadata screening."""

import io
import tarfile

import pytest

from apps.backup.host_restore_files import extract_bundle, project_metadata
from apps.backup.host_restore_transport import RestoreHostError
from tests.backup.recovery_test_support import require_linux_root


METADATA = {
    "manifest.json": b'{"fixture":"path-conflicts"}\n',
    "keys/env.json": b'{"SECRET_KEY":"fixture-only"}\n',
}


def write_tar(path, entries):
    """None denotes a genuine directory header; bytes denote a regular file."""
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as archive:
        for name, raw in entries:
            member = tarfile.TarInfo(name)
            member.type = tarfile.DIRTYPE if raw is None else tarfile.REGTYPE
            member.size = 0 if raw is None else len(raw)
            archive.addfile(member, None if raw is None else io.BytesIO(raw))
    return path


def tree(root):
    return {
        path.relative_to(root).as_posix(): None if path.is_dir() else path.read_bytes()
        for path in root.rglob("*")
    }


@pytest.mark.parametrize("descendant_first", [False, True], ids=["file-first", "child-first"])
def test_payload_file_ancestor_conflict_refuses_during_metadata_screen(tmp_path, descendant_first):
    require_linux_root()
    conflict = [("payload/a", b"ancestor"), ("payload/a/child", b"descendant")]
    if descendant_first:
        conflict.reverse()
    archive = write_tar(tmp_path / "conflict.tar", [
        *METADATA.items(), ("payload/unrelated", b"never projected"), *conflict,
    ])
    metadata = tmp_path / "metadata"

    with pytest.raises(RestoreHostError, match="regular file conflicts with a directory path"):
        project_metadata(archive, metadata)

    # Bounded metadata may already exist; no ordinary payload is projected.
    assert tree(metadata) == {"keys": None, **METADATA}
    assert not (metadata / "payload").exists()
    assert {path.name for path in tmp_path.iterdir()} == {"conflict.tar", "metadata"}


@pytest.mark.parametrize("descendant_first", [False, True], ids=["keys-first", "env-first"])
def test_regular_keys_conflicts_with_required_metadata_directory(tmp_path, descendant_first):
    require_linux_root()
    conflict = [("keys", b"not a directory"), ("keys/env.json", METADATA["keys/env.json"])]
    if descendant_first:
        conflict.reverse()
    archive = write_tar(tmp_path / "keys-conflict.tar", [
        ("manifest.json", METADATA["manifest.json"]),
        ("payload/unrelated", b"never projected"), *conflict,
    ])
    metadata = tmp_path / "metadata"

    with pytest.raises(RestoreHostError, match="regular file conflicts with a directory path"):
        project_metadata(archive, metadata)

    expected = {"manifest.json": METADATA["manifest.json"]}
    if descendant_first:
        expected.update({"keys": None, "keys/env.json": METADATA["keys/env.json"]})
    assert tree(metadata) == expected
    assert not (metadata / "payload").exists()
    assert {path.name for path in tmp_path.iterdir()} == {"keys-conflict.tar", "metadata"}


@pytest.mark.parametrize("directories", ["before", "after", "implied"])
def test_legal_directory_orders_preserve_metadata_and_entire_extracted_tree(tmp_path, directories):
    require_linux_root()
    files = {
        **METADATA,
        "payload/a/child": b"child\x00bytes\n",
        "payload/a/nested/leaf": b"deeper payload",
        "payload/other": b"sibling payload",
    }
    expected_dirs = {"keys": None, "payload": None, "payload/a": None, "payload/a/nested": None}
    entries = list(files.items())
    if directories != "implied":
        expected_dirs["payload/empty"] = None
        explicit = list(expected_dirs.items())
        entries = explicit + entries if directories == "before" else entries + explicit[::-1]
    archive = write_tar(tmp_path / "legal.tar", entries)
    metadata, extracted = tmp_path / "metadata", tmp_path / "bundle"

    project_metadata(archive, metadata)
    assert tree(metadata) == {"keys": None, **METADATA}
    extract_bundle(archive, extracted)
    assert tree(extracted) == {**expected_dirs, **files}
    assert {name: (extracted / name).read_bytes() for name in METADATA} == {
        name: (metadata / name).read_bytes() for name in METADATA
    }
