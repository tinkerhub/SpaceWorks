"""Object-storage image drift guard.

MinIO removed minio/minio and minio/mc from Docker Hub, breaking fresh installs
at compose pull. Keep replacement defaults pinned, overridable and compatible
with the commands that provision storage.
"""

import re
from pathlib import Path

import pytest
import yaml

MOUNTED_REPO_ROOT = Path("/workspace")
REPO_ROOT = (
    MOUNTED_REPO_ROOT
    if (MOUNTED_REPO_ROOT / "backend" / "config" / "settings.py").is_file()
    else Path(__file__).resolve().parent.parent.parent
)
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml")
IMAGE = re.compile(
    r"\$\{([A-Z_][A-Z0-9_]*):-([^${}]+)\}:\$\{([A-Z_][A-Z0-9_]*):-([^${}]+)\}"
)
RELEASE_TAG = re.compile(r"^RELEASE\.\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")
RETIRED_PREFIXES = ("minio/", "docker.io/minio/", "index.docker.io/minio/", "quay.io/minio/")
SERVICES = (
    ("minio", "MINIO_IMAGE", "MINIO_IMAGE_TAG"),
    ("createbuckets", "MC_IMAGE", "MC_IMAGE_TAG"),
)


def _services(manifest):
    path = REPO_ROOT / manifest
    if not path.is_file():  # pragma: no cover - backend image run without the repo mount
        pytest.skip(f"{path} is outside the backend build context")
    return yaml.safe_load(path.read_text(encoding="utf-8-sig"))["services"]


def _image_parts(manifest, service):
    value = _services(manifest)[service]["image"]
    match = IMAGE.fullmatch(value)
    assert match, (
        f"{manifest}: {service} image must use ${{REPO_VAR:-default_repo}}:"
        "${TAG_VAR:-default_tag}; make both repository and tag overridable."
    )
    return match.groups()


@pytest.mark.parametrize("manifest", COMPOSE_FILES)
@pytest.mark.parametrize("service,repo_var,tag_var", SERVICES)
def test_repository_and_tag_are_overridable(manifest, service, repo_var, tag_var):
    actual_repo_var, _, actual_tag_var, _ = _image_parts(manifest, service)
    assert (actual_repo_var, actual_tag_var) == (repo_var, tag_var), (
        f"{manifest}: {service} must use {repo_var} and {tag_var} for image overrides."
    )


@pytest.mark.parametrize("manifest", COMPOSE_FILES)
@pytest.mark.parametrize("service", ("minio", "createbuckets"))
def test_default_repositories_are_usable_repository_names(manifest, service):
    _, repository, _, _ = _image_parts(manifest, service)
    assert not repository.startswith(RETIRED_PREFIXES), (
        f"{manifest}: replace {service}'s retired MinIO repository with a maintained image."
    )
    assert ":" not in repository and "@" not in repository, (
        f"{manifest}: {service} repository must omit tags and digests; use the tag variable."
    )


@pytest.mark.parametrize("manifest", COMPOSE_FILES)
@pytest.mark.parametrize("service", ("minio", "createbuckets"))
def test_default_tags_are_pinned_releases(manifest, service):
    _, _, _, tag = _image_parts(manifest, service)
    assert RELEASE_TAG.fullmatch(tag), (
        f"{manifest}: pin {service} to RELEASE.YYYY-MM-DDTHH-MM-SSZ; "
        "latest and -distroless defaults break the image contract."
    )


@pytest.mark.parametrize("service", ("minio", "createbuckets"))
def test_dev_and_prod_image_defaults_match(service):
    dev = _image_parts(COMPOSE_FILES[0], service)
    prod = _image_parts(COMPOSE_FILES[1], service)
    assert (dev[1], dev[3]) == (prod[1], prod[3]), (
        f"Align {service}'s default repository and tag in dev and prod compose files."
    )


def test_prod_storage_commands_preserve_the_image_contract():
    services = _services("docker-compose.prod.yml")
    assert services["minio"]["command"] == 'server /data --console-address ":9001"', (
        "Restore the production MinIO server command and console port."
    )
    assert services["minio"]["healthcheck"]["test"][:2] == ["CMD", "curl"], (
        "Keep the production curl healthcheck; the server image must supply curl."
    )
    assert services["createbuckets"]["entrypoint"].startswith("/bin/sh -c"), (
        "Keep /bin/sh -c for bucket provisioning; the client image must supply sh and mc."
    )
