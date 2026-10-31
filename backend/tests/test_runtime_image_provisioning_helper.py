"""Real stdlib helper, synthetic Docker inspect transport, private disposable dotenv."""

import json
import os
import stat
import subprocess
import sys

import pytest

from tests.runtime_image_provisioning_support import (
    A, B, REPO, ROOT, digest_in, events, fixture_host, inspect_payload, load_helper,
)


@pytest.fixture
def host(tmp_path, monkeypatch):
    env = fixture_host(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return tmp_path, env


def cli(host, *arguments):
    path, env = host
    return subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/provision-runtime-image.py"),
                           "--env-file", str(path / ".env"), *arguments], env=env,
                          capture_output=True, text=True, timeout=15)


def responses(path, *payloads):
    (path / "payloads.json").write_text(json.dumps({REPO + ":latest": payloads}))


def assert_private_clean(path):
    info = (path / ".env").stat()
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_nlink == 1
    assert not list(path.glob(".runtime-image-*"))


def test_cli_selects_repository_not_config_id_and_accepts_duplicate_candidate(host):
    path, _ = host
    payload = inspect_payload(B)
    payload[0]["RepoDigests"] = ["other.example/unrelated@" + A, REPO + "@" + B, REPO + "@" + B]
    responses(path, payload)
    result = cli(host, "--image", REPO + ":latest")
    assert result.returncode == 0, result.stderr
    assert result.stdout == B + "\n"
    assert digest_in(path) == B
    assert len([event for event in events(path) if event["args"][:2] == ["image", "inspect"]]) == 2
    assert_private_clean(path)


@pytest.mark.parametrize(("image", "expected"), [
    ("registry.example:5443/team/backend:release", REPO),
    ("ubuntu:latest", "docker.io/library/ubuntu"),
    ("index.docker.io/ubuntu:latest", "docker.io/library/ubuntu"),
])
def test_selected_repository_parses_real_tag_and_registry_port(image, expected):
    assert load_helper().selected_repository(image) == expected


@pytest.mark.parametrize("damage", ["missing", "malformed", "ambiguous", "wrong-repo", "entrypoint", "id", "unpublished"])
def test_cli_refuses_invalid_or_unpublished_inspection_without_changing_env(host, damage):
    path, _ = host
    payload = inspect_payload()
    if damage == "missing":
        payload[0].pop("RepoDigests")
    elif damage == "malformed":
        payload[0]["RepoDigests"] = [REPO + "@sha256:bad"]
    elif damage == "ambiguous":
        payload[0]["RepoDigests"].append(REPO + "@" + B)
    elif damage == "wrong-repo":
        payload[0]["RepoDigests"] = ["other.example/backend@" + A]
    elif damage == "entrypoint":
        payload[0]["Config"]["Entrypoint"] = ["sh", "synthetic-inspect-secret"]
    elif damage == "id":
        payload[0]["Id"] = "synthetic-inspect-secret"
    else:
        payload[0]["RepoDigests"] = []
    responses(path, payload)
    before = (path / ".env").read_bytes()
    result = cli(host, "--image", REPO + ":latest")
    assert result.returncode != 0
    assert (path / ".env").read_bytes() == before
    assert "Runtime image provisioning refused:" in result.stderr
    assert "synthetic-inspect-secret" not in result.stdout + result.stderr
    assert "synthetic-do-not-log" not in result.stdout + result.stderr
    assert "RepoDigests" not in result.stdout + result.stderr
    assert_private_clean(path)


@pytest.mark.parametrize("image", [REPO, REPO + ":tag@sha256:" + "a" * 64, "registry.example:70000/backend:tag"])
def test_unusable_image_reference_refuses_before_inspection(host, image):
    path, _ = host
    before = (path / ".env").read_bytes()
    result = cli(host, "--image", image)
    assert result.returncode != 0
    assert (path / ".env").read_bytes() == before
    assert not events(path)


def test_atomic_persistence_preserves_unrelated_bytes_and_fsyncs_private_replacement(host, monkeypatch):
    path, _ = host
    helper = load_helper()
    original = (b"# private comment\r\nSECRET_KEY='synthetic-do-not-log'\r\n"
                b'MULTI="first\r\nSPACEWORKS_OCI_DIGEST=inside-quoted-secret\r\nlast"\r\n'
                b"export SPACEWORKS_OCI_DIGEST='stale'\r\nTAIL=no-newline")
    dotenv = path / ".env"
    dotenv.write_bytes(original)
    inode = dotenv.stat().st_ino
    calls = []
    real_replace, real_fsync = os.replace, os.fsync

    def replace(source, destination, **kwargs):
        assert dotenv.read_bytes() == original
        temporary = path / source
        assert stat.S_IMODE(temporary.stat().st_mode) == 0o600
        assert temporary.stat().st_nlink == 1
        assert len(events(path)) == 2  # Both real Docker inspections already happened.
        calls.append("replace")
        return real_replace(source, destination, **kwargs)

    def fsync(fd):
        calls.append("directory-fsync" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file-fsync")
        return real_fsync(fd)

    monkeypatch.setattr(helper.os, "replace", replace)
    monkeypatch.setattr(helper.os, "fsync", fsync)
    assert helper.persist(dotenv, REPO + ":latest") == A
    assert dotenv.read_bytes() == original.replace(b"export SPACEWORKS_OCI_DIGEST='stale'", b"SPACEWORKS_OCI_DIGEST=" + A.encode())
    assert dotenv.stat().st_ino != inode
    assert calls == ["file-fsync", "replace", "directory-fsync"]
    assert_private_clean(path)


@pytest.mark.parametrize("assignment", [b"SPACEWORKS_OCI_DIGEST=a\nSPACEWORKS_OCI_DIGEST=b\n",
                                        b"SPACEWORKS_OCI_DIGEST='first\nsecond'\n"])
def test_duplicate_or_multiline_digest_assignment_refuses_unchanged(host, assignment):
    path, _ = host
    (path / ".env").write_bytes(assignment)
    result = cli(host, "--image", REPO + ":latest")
    assert result.returncode != 0
    assert (path / ".env").read_bytes() == assignment
    assert_private_clean(path)


@pytest.mark.parametrize("change", ["config-id", "repo-digest", "dotenv"])
def test_second_inspection_or_dotenv_race_refuses_and_removes_temporary(host, change):
    path, env = host
    before = (path / ".env").read_bytes()
    second = inspect_payload(B if change == "repo-digest" else A, witness="d" if change == "config-id" else "c")
    responses(path, inspect_payload(), second)
    if change == "dotenv":
        env["PROVIDER_MUTATE_DOTENV"] = "1"
    result = cli(host, "--image", REPO + ":latest")
    assert result.returncode != 0
    expected = before + b"# concurrent edit\n" if change == "dotenv" else before
    assert (path / ".env").read_bytes() == expected
    assert "changed_during_provisioning" in result.stderr
    assert_private_clean(path)


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "parent", "permissions"])
def test_unsafe_selected_file_or_parent_fails_closed(host, unsafe):
    path, _ = host
    dotenv = path / ".env"
    before = dotenv.read_bytes()
    if unsafe == "symlink":
        target = path / "real.env"
        dotenv.rename(target)
        dotenv.symlink_to(target)
    elif unsafe == "hardlink":
        os.link(dotenv, path / "other.env")
    elif unsafe == "parent":
        path.chmod(0o777)
    else:
        dotenv.chmod(0o644)
    result = cli(host, "--image", REPO + ":latest")
    assert result.returncode != 0
    assert dotenv.read_bytes() == before
    assert "synthetic-do-not-log" not in result.stdout + result.stderr
    assert not list(path.glob(".runtime-image-*"))


def test_clear_removes_previous_digest_without_inspecting_and_warns_full_unavailable(host):
    path, _ = host
    before = (path / ".env").read_bytes()
    result = cli(host, "--clear")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"
    assert (path / ".env").read_bytes() == before.replace(A.encode(), b"")
    assert "signed FULL backup is unavailable" in result.stderr
    assert not events(path)
    assert_private_clean(path)
