"""Real helper refusal at each persistence boundary, with only filesystem faults."""

import os
import stat

import pytest

from tests.runtime_image_provisioning_support import (
    A, B, NEW, REPO, events, fixture_host, load_helper,
)


@pytest.fixture
def private_host(tmp_path, monkeypatch):
    env = fixture_host(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    original = (b"# private comment\r\nSECRET_KEY='synthetic-do-not-log'\r\n"
                b'MULTI="first\r\nSPACEWORKS_OCI_DIGEST=quoted-secret\r\nlast"\r\n'
                b"SPACEWORKS_OCI_DIGEST=" + A.encode() + b"\r\nTAIL=synthetic-tail")
    dotenv = tmp_path / ".env"
    dotenv.write_bytes(original)
    dotenv.chmod(0o600)
    return tmp_path, dotenv, original, dotenv.stat().st_ino, load_helper()


def assert_refusal(path, dotenv, captured, reason, inspections):
    assert captured.out == ""
    assert "Runtime image provisioning refused: " + reason in captured.err
    assert "rerun this helper with --env-file" in captured.err
    for sensitive in ("synthetic-do-not-log", "synthetic-tail", "quoted-secret", A, B,
                      REPO, "RepoDigests", "Entrypoint", "sha256:" + "c" * 64):
        assert sensitive not in captured.out + captured.err
    assert stat.S_IMODE(dotenv.stat().st_mode) == 0o600
    assert dotenv.stat().st_nlink == 1
    assert not list(path.glob(".runtime-image-*"))
    calls = events(path)
    assert len(calls) == inspections
    assert all(call["kind"] == "docker" and
               call["args"] == ["image", "inspect", REPO + ":" + NEW] for call in calls)


def test_file_fsync_failure_refuses_before_replace_preserving_original_inode(private_host, monkeypatch, capsys):
    path, dotenv, original, inode, helper = private_host
    real_fsync = os.fsync

    def fail_file_fsync(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("synthetic-do-not-log RepoDigests")
        return real_fsync(fd)

    monkeypatch.setattr(helper.os, "fsync", fail_file_fsync)
    assert helper.main(["--env-file", str(dotenv), "--image", REPO + ":" + NEW]) != 0
    assert dotenv.read_bytes() == original
    assert dotenv.stat().st_ino == inode
    assert_refusal(path, dotenv, capsys.readouterr(), "dotenv_atomic_update_failed", 1)


def test_replace_failure_refuses_without_false_success_or_temporary_files(private_host, monkeypatch, capsys):
    path, dotenv, original, inode, helper = private_host

    def fail_replace(*args, **kwargs):
        raise OSError("synthetic-do-not-log RepoDigests")

    monkeypatch.setattr(helper.os, "replace", fail_replace)
    assert helper.main(["--env-file", str(dotenv), "--image", REPO + ":" + NEW]) != 0
    assert dotenv.read_bytes() == original
    assert dotenv.stat().st_ino == inode
    assert_refusal(path, dotenv, capsys.readouterr(), "dotenv_atomic_update_failed", 2)


def test_directory_fsync_failure_reports_replaced_complete_private_dotenv(private_host, monkeypatch, capsys):
    path, dotenv, original, inode, helper = private_host
    real_fsync = os.fsync

    def fail_directory_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic-do-not-log RepoDigests")
        return real_fsync(fd)

    monkeypatch.setattr(helper.os, "fsync", fail_directory_fsync)
    assert helper.main(["--env-file", str(dotenv), "--image", REPO + ":" + NEW]) != 0
    assert dotenv.read_bytes() == original.replace(A.encode(), B.encode())
    assert dotenv.stat().st_ino != inode
    assert_refusal(path, dotenv, capsys.readouterr(),
                   "dotenv_replaced_but_directory_fsync_failed_rerun_before_startup", 2)
