"""Filesystem and canonical tar negatives exercise the concrete selected reader."""

from contextlib import contextmanager
import os
from types import SimpleNamespace

import pytest

from apps.tenant_migration import tenant_restore_artifact_files as files
from apps.tenant_migration import tenant_dump_outer_artifact as reader
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_restore_artifact_admission import read_selected_artifact_context
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused
from tests.tenant_migration.x12_selected_test_helpers import SelectedArtifact, private_write, sha


@pytest.mark.parametrize("member", ["path", "inner_path"])
@pytest.mark.parametrize("case", ["relative", "symlink", "hardlink", "directory", "fifo", "mode", "parent_mode", "owner"])
def test_private_selected_and_inner_paths_refuse_unsafe_files(tmp_path, monkeypatch, member, case):
    artifact = SelectedArtifact(tmp_path / "selected")
    path = getattr(artifact, member)
    if case == "relative":
        monkeypatch.chdir(tmp_path)
        setattr(artifact, member, path.relative_to(tmp_path))
    elif case == "symlink":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    elif case == "hardlink":
        os.link(path, path.with_suffix(".linked"))
    elif case == "directory":
        path.unlink()
        path.mkdir(mode=0o700)
    elif case == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif case == "mode":
        path.chmod(0o640)
    elif case == "parent_mode":
        path.parent.chmod(0o750)
    else:
        original_fstat = files.os.fstat
        identity = path.stat()
        def wrong_owner(fd):
            info = original_fstat(fd)
            if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
                values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
                values["st_uid"] = info.st_uid + 1
                return SimpleNamespace(**values)
            return info
        monkeypatch.setattr(files.os, "fstat", wrong_owner)
    with pytest.raises(TenantRestoreRefused):
        read_selected_artifact_context(artifact.inputs, artifact)


@pytest.mark.parametrize("member", ["path", "inner_path"])
def test_private_reader_accepts_owned_parent_alias_but_refuses_final_symlink(tmp_path, member):
    artifact = SelectedArtifact(tmp_path / "selected")
    expected = read_selected_artifact_context(artifact.inputs, artifact)
    alias = tmp_path / "alias"
    alias.symlink_to(artifact.root, target_is_directory=True)
    original = getattr(artifact, member)
    setattr(artifact, member, alias / original.name)
    # A parent alias is allowed: private ownership and SHA bind the pinned file.
    assert read_selected_artifact_context(artifact.inputs, artifact) == expected
    saved = original.with_suffix(".owned")
    original.rename(saved)
    original.symlink_to(saved)
    # Even through that alias, the final component must be a nofollow regular file.
    with pytest.raises(TenantRestoreRefused):
        read_selected_artifact_context(artifact.inputs, artifact)


def test_oversize_inner_refuses_before_reading_payload(tmp_path, monkeypatch):
    artifact = SelectedArtifact(tmp_path / "selected")
    with artifact.inner_path.open("r+b") as handle:
        handle.truncate(files.MAX_INNER_MANIFEST_BYTES + 1)
    with pytest.raises(TenantRestoreRefused):
        read_selected_artifact_context(artifact.inputs, artifact)


def test_outer_digest_and_manifest_use_one_descriptor_despite_path_swap(tmp_path, monkeypatch):
    artifact = SelectedArtifact(tmp_path / "selected")
    opened, digested, canonical = [], [], []
    original_open = reader.open_artifact_file
    original_digest = reader._handle_digest
    original_canonical = reader._verify_canonical_tar
    @contextmanager
    def observe_open(path, **kwargs):
        with original_open(path, **kwargs) as handle:
            opened.append(handle.fileno())
            yield handle
    def digest(handle):
        digested.append(handle.fileno())
        result = original_digest(handle)
        if len(digested) == 1:
            # Renaming a pinned descriptor changes ctime, so preserve its name by
            # unlinking the alias instead; drift may refuse but cannot read replacement.
            artifact.path.unlink()
            private_write(artifact.path, b"replacement must never be admitted")
        return result
    def verify(handle, *args):
        canonical.append(handle.fileno())
        return original_canonical(handle, *args)
    monkeypatch.setattr(reader, "open_artifact_file", observe_open)
    monkeypatch.setattr(reader, "_handle_digest", digest)
    monkeypatch.setattr(reader, "_verify_canonical_tar", verify)
    # Unlink changes nlink/ctime on real filesystems: the descriptor continuity guard refuses.
    with pytest.raises(TenantDumpVerificationError):
        reader.read_outer_manifest(artifact.path, expected_artifact_sha256=artifact.inputs.artifact_sha256)
    assert len(opened) == 1
    assert len(digested) == 2
    assert canonical == opened
    assert digested == opened * 2
    assert artifact.path.read_bytes() == b"replacement must never be admitted"


def test_inplace_artifact_drift_between_digest_and_parse_refuses(tmp_path, monkeypatch):
    artifact = SelectedArtifact(tmp_path / "selected")
    original = reader._handle_digest
    calls = []
    def drift(handle):
        calls.append(handle.fileno())
        result = original(handle)
        if len(calls) == 1:
            with artifact.path.open("r+b") as writer:
                writer.seek(0)
                writer.write(b"corruption")
        return result
    monkeypatch.setattr(reader, "_handle_digest", drift)
    with pytest.raises(TenantDumpVerificationError):
        reader.read_outer_manifest(artifact.path, expected_artifact_sha256=artifact.inputs.artifact_sha256)


@pytest.mark.parametrize("case", ["header_mode", "padding", "trailing", "extra_record", "payload", "selected_sha"])
def test_actual_wrapper_sha_and_canonical_bytes_are_all_required(tmp_path, case):
    artifact = SelectedArtifact(tmp_path / "selected")
    data = bytearray(artifact.path.read_bytes())
    if case == "header_mode":
        # A valid alternate tar header is still outside the canonical wrapper.
        import tarfile
        header = tarfile.TarInfo.frombuf(bytes(data[:512]), "utf-8", "strict")
        header.mode = 0o644
        data[:512] = header.tobuf(format=tarfile.USTAR_FORMAT)
    elif case == "padding":
        manifest_end = 512 + len(reader.canonical_manifest_bytes(artifact.outer))
        data[manifest_end] = 1
    elif case == "trailing":
        data[-1] = 1
    elif case == "extra_record":
        data.extend(b"\0" * 10240)
    elif case == "payload":
        offset = data.index(b"opaque framing")
        data[offset] ^= 1
    private_write(artifact.path, bytes(data))
    # Recompute the selected SHA for canonical negatives: a matching digest alone is insufficient.
    expected = "f" * 64 if case == "selected_sha" else sha(data)
    with pytest.raises(TenantDumpVerificationError):
        reader.read_outer_manifest(artifact.path, expected_artifact_sha256=expected)
