#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/env-file.sh"
case "$ROOT" in
  *"'"*) printf 'ERROR: the install path cannot contain a single quote.\n' >&2; exit 1 ;;
  *$'\r'*|*$'\n'*|*'%'*) printf 'ERROR: the install path cannot contain CR, LF, or %%.\n' >&2; exit 1 ;;
esac
command -v crontab >/dev/null 2>&1 || {
  printf 'ERROR: crontab is unavailable; schedule scripts/update.sh every seven days with your service manager.\n' >&2
  exit 1
}

# Resolve and validate the active Compose layer before changing application state or the crontab.
# Embedding only a validated value prevents cron injection and preserves the TLS topology on updates.
LAYER="${SPACEWORKS_COMPOSE_LAYER:-}"
if [[ -z "$LAYER" && "${SPACEWORKS_COMPOSE_BUILD_LAYER:-0}" == "1" ]]; then
  LAYER="build"
fi
LAYER="${LAYER:-none}"
case "$LAYER" in
  none|build|tls|build-tls|saas|build-saas) ;;
  *)
    printf 'ERROR: unsupported Compose layer: %s\n' "$LAYER" >&2
    exit 1
    ;;
esac

SCHEDULE="${SPACEWORKS_UPDATE_SCHEDULE:-}"
if [[ -z "$SCHEDULE" ]]; then
  SCHEDULE="$(env_file_get "$ROOT/.env" SPACEWORKS_UPDATE_SCHEDULE)" || exit 1
fi
SCHEDULE="${SCHEDULE:-0 3 * * 0}"
SCHEDULE="$(validate_cron_schedule "$SCHEDULE")" || {
  printf 'ERROR: invalid SPACEWORKS_UPDATE_SCHEDULE; use a valid five-field cron schedule.\n' >&2
  exit 1
}

COMPOSE=("$ROOT/scripts/spaceworks-compose.sh" bundled)
"${COMPOSE[@]}" run --rm --no-deps -T backend --role management python manage.py update_control set-auto on >/dev/null

MARKER="# Space Works automatic production update"
if [[ "$LAYER" == "none" ]]; then
  JOB="$SCHEDULE cd '$ROOT' && bash '$ROOT/scripts/update.sh' >> '$ROOT/backups/auto-update.log' 2>&1"
else
  JOB="$SCHEDULE cd '$ROOT' && SPACEWORKS_COMPOSE_LAYER=$LAYER bash '$ROOT/scripts/update.sh' >> '$ROOT/backups/auto-update.log' 2>&1"
fi
existing="$(crontab -l 2>/dev/null || true)"
filtered="$(printf '%s\n' "$existing" | grep -v -F "$MARKER" | grep -v -F "$ROOT/scripts/update.sh" || true)"

mkdir -p "$ROOT/backups"
{
  printf '%s\n' "$filtered"
  printf '%s\n' "$MARKER"
  printf '%s\n' "$JOB"
} | sed '/^[[:space:]]*$/N;/^\n$/D' | crontab -

printf 'Automatic Space Works updates are enabled; the host checks for a new release on schedule: %s.\n' "$SCHEDULE"
