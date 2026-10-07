"""Host provisioning and unattended updates must follow the same configured images."""

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "install.sh").exists(),
    reason="host-only: the repository root is not in the backend image",
)
_OVERRIDES = ("SPACEWORKS_REPOSITORY", "MAKERSPACE_BACKEND_IMAGE", "MAKERSPACE_IMAGE_TAG")


def _resolve(tmp_path, function, dotenv=None, version=None, environment=None):
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    if version is not None:
        (tmp_path / ".spaceworks-version").write_text(version, encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key not in _OVERRIDES}
    return subprocess.run(
        [shutil.which("bash") or "bash", "-c", 'source "$1"; source "$2"; "$3" "$4"', "image-test",
         (ROOT / "scripts/env-file.sh").as_posix(),
         (ROOT / "scripts/host-image.sh").as_posix(), function, tmp_path.as_posix()],
        env={**env, "BASH_ENV": "", **(environment or {})},
        capture_output=True, text=True, timeout=10,
    )


@pytest.mark.parametrize(
    ("dotenv", "shell", "expected"),
    [(None, None, "SpaceWorks-HQ/SpaceWorks"),
     ("Fork/SpaceWorks", None, "Fork/SpaceWorks"),
     ("File/Repo", "Shell/Repo", "Shell/Repo")],
    ids=["default", "dotenv", "shell-wins"],
)
def test_repository_precedence(tmp_path, dotenv, shell, expected):
    """A fork's releases must be selectable from persisted settings and shell overrides."""
    result = _resolve(
        tmp_path, "resolve_spaceworks_repository",
        dotenv=None if dotenv is None else f"SPACEWORKS_REPOSITORY={dotenv}\n",
        environment={} if shell is None else {"SPACEWORKS_REPOSITORY": shell},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected + "\n"


@pytest.mark.parametrize("repository", ["owner", "owner/repo/extra", "owner/repo;evil", "owner/re po"])
@pytest.mark.parametrize("source", ["shell", "dotenv"])
def test_invalid_repository_is_rejected(tmp_path, repository, source):
    """An invalid owner/repo must not become part of a GitHub release URL."""
    result = _resolve(
        tmp_path, "resolve_spaceworks_repository",
        dotenv=f"SPACEWORKS_REPOSITORY={repository}\n" if source == "dotenv" else None,
        environment={"SPACEWORKS_REPOSITORY": repository} if source == "shell" else {},
    )
    assert result.returncode != 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("dotenv", "shell", "expected"),
    [(None, None, "ghcr.io/spaceworks-hq/spaceworks-backend"),
     ("ghcr.io/fork/backend", None, "ghcr.io/fork/backend"),
     ("ghcr.io/file/backend", "ghcr.io/shell/backend", "ghcr.io/shell/backend")],
    ids=["default", "dotenv", "shell-wins"],
)
def test_backend_image_precedence(tmp_path, dotenv, shell, expected):
    """Host configuration must use the backend image the operator selected for deployment."""
    result = _resolve(
        tmp_path, "resolve_backend_image",
        dotenv=None if dotenv is None else f"MAKERSPACE_BACKEND_IMAGE={dotenv}\n",
        environment={} if shell is None else {"MAKERSPACE_BACKEND_IMAGE": shell},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected + "\n"


@pytest.mark.parametrize(
    ("image", "valid"),
    [("registry.example.org:5000/spaceworks-backend", True),
     ("localhost:5000/team/backend", True),
     ("ghcr.io/fork/backend:latest", False),
     ("backend:5000", False)],
    ids=["registry-port", "localhost-port", "appended-tag", "bare-tag"],
)
def test_backend_image_allows_registry_port_but_not_a_tag(tmp_path, image, valid):
    """A private registry port is part of the name; a trailing tag belongs in MAKERSPACE_IMAGE_TAG."""
    result = _resolve(
        tmp_path, "resolve_backend_image",
        environment={"MAKERSPACE_BACKEND_IMAGE": image},
    )
    assert (result.returncode == 0) is valid, result.stderr
    assert result.stdout == (image + "\n" if valid else "")


@pytest.mark.parametrize("source", ["shell", "dotenv"])
def test_backend_image_rejects_uppercase(tmp_path, source):
    """Container repository names must be lowercase rather than fail later during a pull."""
    image = "ghcr.io/Fork/backend"
    result = _resolve(
        tmp_path, "resolve_backend_image",
        dotenv=f"MAKERSPACE_BACKEND_IMAGE={image}\n" if source == "dotenv" else None,
        environment={"MAKERSPACE_BACKEND_IMAGE": image} if source == "shell" else {},
    )
    assert result.returncode != 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("shell", "dotenv", "version", "expected"),
    [(None, None, None, "latest"),
     (None, None, "0.7.5-main.1.abcdef123456\n", "0.7.5-main.1.abcdef123456"),
     (None, "env-tag", "version-tag\n", "env-tag"),
     ("shell-tag", "env-tag", "version-tag\n", "shell-tag")],
    ids=["latest", "version-file", "dotenv-wins", "shell-wins"],
)
def test_image_tag_precedence(tmp_path, shell, dotenv, version, expected):
    """Provisioning must not silently configure latest over an installed immutable version."""
    result = _resolve(
        tmp_path, "resolve_image_tag", version=version,
        dotenv=None if dotenv is None else f"MAKERSPACE_IMAGE_TAG={dotenv}\n",
        environment={} if shell is None else {"MAKERSPACE_IMAGE_TAG": shell},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected + "\n"


@pytest.mark.parametrize(
    ("dotenv", "expected"),
    [("export MAKERSPACE_IMAGE_TAG=stable\n", "0.8.2-main.1.abcdefabcdef"),
     ("  MAKERSPACE_IMAGE_TAG=stable\n", "0.8.2-main.1.abcdefabcdef"),
     ("MAKERSPACE_IMAGE_TAG=\n", "0.8.2-main.1.abcdefabcdef"),
     ("MAKERSPACE_IMAGE_TAG=pinned # note\n", "pinned"),
     ('MAKERSPACE_IMAGE_TAG=""\n', "latest"),
     ("MAKERSPACE_IMAGE_TAG= # unset\n", "latest")],
    ids=["export-form", "indented", "empty", "plain-with-comment",
         "quoted-empty", "comment-only"],
)
def test_image_tag_follows_the_compose_wrapper_rule(tmp_path, dotenv, expected):
    """spaceworks-compose.sh only lets a plain non-empty .env line beat the version marker."""
    result = _resolve(
        tmp_path, "resolve_image_tag",
        dotenv=dotenv, version="0.8.2-main.1.abcdefabcdef\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected + "\n"


@pytest.mark.parametrize("source", ["shell", "dotenv", "version"])
@pytest.mark.parametrize("tag", ["bad:tag", "bad/tag", "bad;tag"])
def test_invalid_tag_is_rejected_at_every_source(tmp_path, source, tag):
    """Bad tags must fail resolution instead of escaping into the Docker image reference."""
    result = _resolve(
        tmp_path, "resolve_image_tag",
        dotenv=f"MAKERSPACE_IMAGE_TAG={tag}\n" if source == "dotenv" else None,
        version=tag if source == "version" else None,
        environment={"MAKERSPACE_IMAGE_TAG": tag} if source == "shell" else {},
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_host_entrypoints_use_shared_release_and_image_resolution():
    """Shared precedence is ineffective if a host entrypoint still hardcodes upstream."""
    updater = (ROOT / "scripts/update.sh").read_text(encoding="utf-8")
    assert re.search(r'REPOSITORY="\$\(resolve_spaceworks_repository "\$ROOT"\)"', updater)
    assert 'RELEASE_API="https://api.github.com/repos/$REPOSITORY/releases/latest"' in updater
    assert "repos/SpaceWorks-HQ/SpaceWorks" not in updater
    initializer = (ROOT / "scripts/init-host-orchestration.sh").read_text(encoding="utf-8")
    assert 'image="$(resolve_backend_image "$ROOT")"' in initializer
    assert 'tag="$(resolve_image_tag "$ROOT")"' in initializer
    assert 'HOST_CONFIG_IMAGE="${image}:${tag}"' in initializer
