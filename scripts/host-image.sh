# Shared fork-aware release/image resolution; source scripts/env-file.sh first.

SPACEWORKS_DEFAULT_REPOSITORY="SpaceWorks-HQ/SpaceWorks"
SPACEWORKS_DEFAULT_BACKEND_IMAGE="ghcr.io/spaceworks-hq/spaceworks-backend"

spaceworks_repository_is_valid() {
  local LC_ALL=C
  [[ "$1" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
    printf 'ERROR: invalid Space Works repository: %s\n' "$1" >&2; return 1
  }
}

spaceworks_image_is_valid() {
  local LC_ALL=C
  # An optional registry port is allowed only before a path component; a bare
  # trailing ":value" would be an image tag, which belongs in MAKERSPACE_IMAGE_TAG.
  [[ "$1" =~ ^[a-z0-9][a-z0-9._-]*((:[0-9]{1,5})?(/[a-z0-9][a-z0-9._-]*)+)?$ ]] || {
    printf 'ERROR: invalid Space Works image name: %s\n' "$1" >&2; return 1
  }
}

spaceworks_tag_is_valid() {
  local LC_ALL=C
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
    printf 'ERROR: invalid Space Works image tag: %s\n' "$1" >&2; return 1
  }
}

resolve_spaceworks_repository() {
  local root="$1" repository="${SPACEWORKS_REPOSITORY:-}"
  if [[ -z "$repository" ]]; then
    repository="$(env_file_get "$root/.env" SPACEWORKS_REPOSITORY)" || return 1
  fi
  repository="${repository:-$SPACEWORKS_DEFAULT_REPOSITORY}"
  spaceworks_repository_is_valid "$repository" || return 1
  printf '%s\n' "$repository"
}

resolve_backend_image() {
  local root="$1" image="${MAKERSPACE_BACKEND_IMAGE:-}"
  if [[ -z "$image" ]]; then
    image="$(env_file_get "$root/.env" MAKERSPACE_BACKEND_IMAGE)" || return 1
  fi
  image="${image:-$SPACEWORKS_DEFAULT_BACKEND_IMAGE}"
  spaceworks_image_is_valid "$image" || return 1
  printf '%s\n' "$image"
}

resolve_image_tag() {
  local root="$1" tag="${MAKERSPACE_IMAGE_TAG:-}" dotenv_decides=0
  # Mirror scripts/spaceworks-compose.sh exactly: a raw `MAKERSPACE_IMAGE_TAG=<anything>`
  # line stops it exporting the version marker, and Compose then resolves .env itself
  # (an empty or quoted-empty value falls to its `:-latest` default). Any other line
  # form leaves the marker exported. Any other rule here would build host
  # configuration from a different image than the stack runs.
  if [[ -z "$tag" && -f "$root/.env" ]] && grep -q '^MAKERSPACE_IMAGE_TAG=.' "$root/.env"; then
    dotenv_decides=1
    tag="$(env_file_get "$root/.env" MAKERSPACE_IMAGE_TAG)" || return 1
  fi
  if [[ -z "$tag" && "$dotenv_decides" == 0 && -f "$root/.spaceworks-version" ]]; then
    tag="$(tr -d '[:space:]' < "$root/.spaceworks-version")" || {
      printf 'ERROR: cannot read Space Works version file.\n' >&2; return 1
    }
  fi
  tag="${tag:-latest}"
  spaceworks_tag_is_valid "$tag" || return 1
  printf '%s\n' "$tag"
}
