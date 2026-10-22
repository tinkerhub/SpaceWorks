#!/usr/bin/env bash
# Apply the newest fully-published Space Works release to a production Compose stack.
set -euo pipefail

UPDATE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SPACEWORKS_UPDATE_INSTALL_DIR:-$(cd "$UPDATE_SCRIPT_DIR/.." && pwd)}"
cd "$ROOT"
export SPACEWORKS_UPDATE_INSTALL_DIR="$ROOT"

OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-/var/lib/spaceworks/ops}"
COMPOSE=("$ROOT/scripts/spaceworks-compose.sh" bundled)
LOCK_DIR="$ROOT/.spaceworks-update.lock"
VERSION_FILE="$ROOT/.spaceworks-version"
update_claimed=0
update_complete=0
deployment_started=0
previous_version=""
UPDATE_LOCK_HELD=0
UPDATE_LOCK_OVERRIDE=0
MODULE_REQUESTED=0
MODULE_ONLY=0
MODULE_MODE=interactive
MODULE_INTERACTIVE=0
MODULE_MAKERSPACE=""
MODULE_ALL_MAKERSPACES=0
MODULE_WITHOUT=""
MODULE_CONFIRM_REMOVALS=0
NO_MODULE_CHANGES=0

say() { printf '[Space Works updater] %s\n' "$*"; }
warn() { printf '[Space Works updater] WARNING: %s\n' "$*" >&2; }
die() { printf '[Space Works updater] ERROR: %s\n' "$*" >&2; exit 1; }
source "$UPDATE_SCRIPT_DIR/update-lock.sh"
source "$UPDATE_SCRIPT_DIR/module-selection.sh"
source "$UPDATE_SCRIPT_DIR/env-file.sh"
source "$UPDATE_SCRIPT_DIR/host-image.sh"
REPOSITORY="$(resolve_spaceworks_repository "$ROOT")" || die "Invalid SPACEWORKS_REPOSITORY."
export SPACEWORKS_REPOSITORY="$REPOSITORY"
OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-$(env_file_get "$ROOT/.env" SPACEWORKS_OPS_HOST_DIR)}"
OPS_DIR="${OPS_DIR:-/var/lib/spaceworks/ops}"
export SPACEWORKS_OPS_HOST_DIR="$OPS_DIR"
BACKEND_IMAGE="$(resolve_backend_image "$ROOT")" || die "Invalid backend image."
FRONTEND_IMAGE="$(resolve_frontend_image "$ROOT")" || die "Invalid frontend image."
RELEASE_API="https://api.github.com/repos/$REPOSITORY/releases/latest"
source "$UPDATE_SCRIPT_DIR/retire-update-tombstone.sh"
source "$UPDATE_SCRIPT_DIR/retire-update-polling.sh"
source "$UPDATE_SCRIPT_DIR/install-host-bundle.sh"
source "$UPDATE_SCRIPT_DIR/refresh-proxy-config.sh"

force_arg=()
while (($# > 0)); do
  case "$1" in
    --force) force_arg=(--force) ;;
    --modules) MODULE_REQUESTED=1; MODULE_MODE=interactive ;;
    --modules-only) MODULE_REQUESTED=1; MODULE_ONLY=1 ;;
    --no-module-changes) NO_MODULE_CHANGES=1 ;;
    --all-modules) MODULE_REQUESTED=1; MODULE_MODE=all ;;
    --without=*)
      MODULE_REQUESTED=1; MODULE_WITHOUT="${1#*=}"
      [[ "$MODULE_MODE" == all ]] || MODULE_MODE=without
      ;;
    --makerspace)
      shift; (($# > 0)) || die "--makerspace requires a slug."
      MODULE_MAKERSPACE="$1"; MODULE_REQUESTED=1
      ;;
    --all-makerspaces) MODULE_ALL_MAKERSPACES=1; MODULE_REQUESTED=1 ;;
    --confirm-removals) MODULE_CONFIRM_REMOVALS=1 ;;
    --override-lock) UPDATE_LOCK_OVERRIDE=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/update.sh [--force] [module options]
  --force                   reinstall the latest release even if it is already installed
  --modules                 interactively review current modules
  --modules-only            change modules without checking for a release
  --all-modules             enable every optional module
  --without=key1,key2       keep current state, or all modules, except these keys
  --makerspace <slug>       target one makerspace
  --all-makerspaces         explicitly target every makerspace
  --confirm-removals        acknowledge retained-data module removals non-interactively
  --no-module-changes       update images only
  --override-lock           clear a verified stale/wedged portable update lock
EOF
      exit 0
      ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done
[[ "$MODULE_ALL_MAKERSPACES" == 0 || -z "$MODULE_MAKERSPACE" ]] \
  || die "Use either --makerspace or --all-makerspaces, not both."
[[ "$NO_MODULE_CHANGES" == 0 || "$MODULE_REQUESTED" == 0 ]] \
  || die "--no-module-changes cannot be combined with module-selection options."
if [[ "$MODULE_REQUESTED" == 0 && "$NO_MODULE_CHANGES" == 0 && -t 0 && -t 1 ]]; then
  MODULE_REQUESTED=1
  MODULE_MODE=interactive
fi
if [[ "$MODULE_MODE" == interactive ]]; then
  [[ "$MODULE_REQUESTED" == 0 || ( -t 0 && -t 1 ) ]] \
    || die "Interactive module selection needs a terminal; use --all-modules/--without or --no-module-changes."
  MODULE_INTERACTIVE="$MODULE_REQUESTED"
fi

wait_for_backend() {
  local _
  for _ in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T backend python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/readiness/', timeout=3).read()" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

command -v docker >/dev/null 2>&1 || die "Docker is not installed."
command -v curl >/dev/null 2>&1 || die "curl is required to check GitHub releases."
cleanup() {
  exit_code=$?
  trap - EXIT
  set +e
  if [[ "$update_claimed" == 1 && "$update_complete" == 0 ]]; then
    failure_message="Host update failed. Check the terminal output or Actions job log."
    if [[ "$deployment_started" == 1 && \
      "$previous_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ ]]; then
      say "Update failed; rolling application containers back to $previous_version."
      export MAKERSPACE_IMAGE_TAG="$previous_version"
      "${COMPOSE[@]}" pull backend worker beat frontend || \
        say "Could not refresh previous images; trying the host's cached copies."
      # Put back the previous proof byte-for-byte; forward database changes stay in place.
      # Regenerating it would run the OLD image's installer, which may predate its fix.
      producer_marker 'if [ -f /p/.producer-capability.previous ]; then mv -f /p/.producer-capability.previous /p/producer-capability.json; fi' \
        || say "Could not restore the previous producer proof."
      if "${COMPOSE[@]}" up -d --no-deps backend worker beat frontend && wait_for_backend; then
        say "Rollback complete: $previous_version is healthy."
        failure_message="Update failed; application containers rolled back to $previous_version. The database backup was retained."
      else
        say "ERROR: automatic rollback to $previous_version failed."
        failure_message="Update and automatic rollback failed. Restore the database backup and previous image tag manually."
      fi
    fi
    say "$failure_message"
  fi
  release_update_lock
  exit "$exit_code"
}
# Root-owned producer proof: saved before an update replaces it, restored on rollback.
HOST_STATE_DIR="${SPACEWORKS_HOST_STATE_DIR:-$(env_file_get "$ROOT/.env" SPACEWORKS_HOST_STATE_DIR)}"
HOST_STATE_DIR="${HOST_STATE_DIR:-/var/lib/spaceworks/host}"
# init-host-orchestration.sh reads only the environment; it must write the same directory.
export SPACEWORKS_HOST_STATE_DIR="$HOST_STATE_DIR"
producer_marker() {
  docker run --rm --user 0:0 --entrypoint sh -v "$HOST_STATE_DIR/public:/p" \
    "$BACKEND_IMAGE:${version:-$previous_version}" -c "$1"
}
trap cleanup EXIT
acquire_update_lock
# Before setup created backups/ itself, Docker made it root-owned for the db bind mount,
# and every update by the non-root install owner then died on chmod.
if [[ -d "$ROOT/backups" && ! -O "$ROOT/backups" ]]; then
  docker run --rm --user 0:0 --entrypoint chown -v "$ROOT/backups:/b" \
    "$BACKEND_IMAGE:$(resolve_image_tag "$ROOT")" "$(id -u):$(id -g)" /b \
    || die "backups/ is not owned by $(id -un) and could not be repaired; chown it, then rerun."
fi
# Preserve the selected topology for unattended updates, including upgraded TLS hosts.
layer="${SPACEWORKS_COMPOSE_LAYER:-}"
[[ -n "$layer" || "${SPACEWORKS_COMPOSE_BUILD_LAYER:-0}" != 1 ]] || layer=build
if [[ -n "$layer" ]]; then
  case "$layer" in
    none|build|tls|build-tls|saas|build-saas) printf '%s\n' "$layer" > "$ROOT/.spaceworks-layer" ;;
    *) die "Invalid Compose layer." ;;
  esac
fi
retire_update_polling

if [[ "$MODULE_REQUESTED" == 1 ]]; then
  module_targets || die "Module targeting failed; no release or module changes were made."
  if [[ "$MODULE_ALL_MAKERSPACES" == 0 ]]; then
    MODULE_MAKERSPACE="${MODULE_TARGETS[0]}"
  fi
fi
if [[ "$MODULE_ONLY" == 1 ]]; then
  change_modules || die "One or more requested module changes were not applied."
  say "Module review complete."
  exit 0
fi

# The installer pins the release whose archive it already staged, so host files and images
# can never come from two different releases. Every other run follows GitHub's latest.
if [[ -n "${SPACEWORKS_PINNED_RELEASE:-}" ]]; then
  tag="$SPACEWORKS_PINNED_RELEASE"
else
  release_json="$(curl --fail --silent --show-error --location \
    --connect-timeout 10 --max-time 30 --retry 2 --retry-delay 5 \
    --header 'Accept: application/vnd.github+json' \
    --header 'User-Agent: spaceworks-self-host-updater' \
    "$RELEASE_API")"
  tag="$(printf '%s' "$release_json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
fi
version="${tag#v}"

if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ ]]; then
  die "GitHub latest release returned an unexpected tag: ${tag:-<empty>}"
fi

current=""
if [[ -f "$VERSION_FILE" ]]; then
  current="$(tr -d '[:space:]' < "$VERSION_FILE")"
fi
previous_version="$current"

if [[ ${#force_arg[@]} == 0 && "$current" == "$version" ]]; then
  say "$version is already installed."
  apply_release_proxy_config "$tag"
  if [[ "$MODULE_REQUESTED" == 1 ]]; then
    change_modules || die "One or more requested module changes were not applied."
    say "Module review complete."
  fi
  exit 0
fi
update_claimed=1

say "Updating ${current:-untracked installation} to $version."
mkdir -p "$ROOT/backups"
chmod 700 "$ROOT/backups"
"${COMPOSE[@]}" up -d --wait db
backup_name="pre-update-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
say "Creating database backup backups/$backup_name."
# Restore can switch to a sibling database; back up the active pointer, not bootstrap DB.
# Read the host pointer itself (0640, setup group) so a stopped backend cannot block recovery.
pointer_url="$(env_file_get "$OPS_DIR/database-pointer.env" DATABASE_URL)" \
  || die "Cannot read $OPS_DIR/database-pointer.env; update cancelled."
backup_database="$(printf '%s' "$pointer_url" | python3 -c \
  "import sys, urllib.parse; print(urllib.parse.unquote(urllib.parse.urlsplit(sys.stdin.read().strip()).path.lstrip('/')))")"
backup_database="$(printf '%s' "$backup_database" | tr -d '\r\n')"
# Same identifier rule as the host marker (apps/backup/host_marker.py), within Postgres's 63.
database_name_re='^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
[[ "$backup_database" =~ $database_name_re ]] \
  || die "The active database pointer has an invalid database name; update cancelled."
"${COMPOSE[@]}" exec -T -e "SPACEWORKS_BACKUP_DATABASE=$backup_database" db sh -c \
  'set -e; raw="/backups/'"$backup_name"'.raw"; trap '\''rm -f "$raw"'\'' EXIT; pg_dump -U "$POSTGRES_USER" "$SPACEWORKS_BACKUP_DATABASE" > "$raw"; test -s "$raw"; gzip -c "$raw" > "/backups/'"$backup_name"'"'
"${COMPOSE[@]}" exec -T db test -s "/backups/$backup_name" \
  || die "Database backup was not created; update cancelled."

export MAKERSPACE_IMAGE_TAG="$version"

# Pull both release images directly, before host files or the producer proof change: every
# service runs one of these two images, so a failed pull leaves this host untouched.
docker pull "$BACKEND_IMAGE:$version"
docker pull "$FRONTEND_IMAGE:$version"
retire_update_tombstone
install_staged_host_bundle "$(cd "$UPDATE_SCRIPT_DIR/.." && pwd)"
# From here the producer proof changes, so any failure must take the rollback path that
# restores the previous proof. No further pull: both release images are already local.
producer_marker 'rm -f /p/.producer-capability.previous; if [ -f /p/producer-capability.json ]; then cp -p /p/producer-capability.json /p/.producer-capability.previous; fi' \
  || die "Could not save the current producer proof; update cancelled."
deployment_started=1
# New Compose hashes and producer proof must precede Django startup.
bash "$ROOT/scripts/init-host-orchestration.sh"
COMPOSE=("$ROOT/scripts/spaceworks-compose.sh" bundled)

say "Running migrations and replacing application containers."
"${COMPOSE[@]}" up -d

wait_for_backend || die "Release $version did not become ready. The backup is backups/$backup_name."

printf '%s\n' "$version" > "$VERSION_FILE"
update_complete=1
producer_marker 'rm -f /p/.producer-capability.previous' || true
find "$ROOT/backups" -maxdepth 1 -type f -name 'pre-update-*.sql.gz' -mtime +14 -delete
say "Release update complete: $version."
apply_release_proxy_config "$tag"
if [[ "$MODULE_REQUESTED" == 1 ]]; then
  change_modules || die "Release $version is healthy, but one or more module changes were not applied."
fi
say "Update complete: $version."
