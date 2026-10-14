#!/usr/bin/env bash
# A signed delivery is only a wake-up signal. update.sh rechecks GitHub itself.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/env-file.sh"
OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-$(env_file_get "$ROOT/.env" SPACEWORKS_OPS_HOST_DIR)}"
OPS_DIR="${OPS_DIR:-/var/lib/spaceworks/ops}"
REQUEST_DIR="${SPACEWORKS_DEPLOY_REQUEST_DIR:-$OPS_DIR/deploy-requests}"
# A delivery can arrive before release.yml promotes the release to "latest"; keep it this
# long so later runs see the promotion. Failed runs keep requests for a day of retries.
PROMOTION_WAIT_MINUTES=60
FAILURE_RETRY_MINUTES=1440
[[ -d "$REQUEST_DIR" ]] || exit 0
LOCK_DIR="$ROOT/.spaceworks-deploy.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  owner=""
  owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"; owner="${owner//[[:space:]]/}"
  if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
    rm -f "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" 2>/dev/null || exit 0
    mkdir "$LOCK_DIR" 2>/dev/null || exit 0
  else
    exit 0
  fi
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"
trap 'rm -f "$LOCK_DIR/pid"; rmdir "$LOCK_DIR"' EXIT
shopt -s nullglob
requests=("$REQUEST_DIR"/*.json)
((${#requests[@]})) || exit 0
# Keep the batch until the updater has waited for existing host operations. A crash
# before it starts leaves the requests queued; arrivals during the run remain separate.
mkdir -p "$ROOT/backups"
chmod 700 "$ROOT/backups"
# Release tags end in -main.<run>.<sha12>; the run number only grows. The receiver wrote the
# tag after validating it. It decides only when a request is satisfied, never what deploys.
installed_run() {
  sed -n 's/^[0-9]*\.[0-9]*\.[0-9]*-main\.\([0-9]*\)\.[0-9a-f]\{12\}$/\1/p' \
    "$ROOT/.spaceworks-version" 2>/dev/null | head -n 1
}
request_run() {
  sed -n 's/.*"tag"[[:space:]]*:[[:space:]]*"v[0-9]*\.[0-9]*\.[0-9]*-main\.\([0-9]*\)\.[0-9a-f]\{12\}".*/\1/p' \
    "$1" 2>/dev/null | head -n 1
}
status=75
while [[ "$status" == 75 ]]; do
  status=0
  # No --force: a delivery deploys only a release newer than the installed one.
  SPACEWORKS_DEPLOY_WAIT=1 bash "$ROOT/scripts/update.sh" --no-module-changes \
    >> "$ROOT/backups/deploy.log" 2>&1 || status=$?
  [[ "$status" != 75 ]] || sleep 10
done
if [[ "$status" == 0 ]]; then
  # A request is satisfied once the installed release is at or past the one it announced.
  # A host that was behind may have just installed an older "latest": keep the newer request.
  current="$(installed_run)"
  for request in "${requests[@]}"; do
    wanted="$(request_run "$request")"
    if [[ -z "$wanted" ]] || { [[ -n "$current" ]] && ((10#$current >= 10#$wanted)); }; then
      rm -f -- "$request"
    fi
  done
fi
# A release not promoted to "latest" yet, or a failed update: retry later, but drop requests
# past their window so a release that never becomes "latest" cannot loop forever. The pause
# also keeps unauthenticated GitHub API checks well under the hourly limit.
if [[ "$status" == 0 ]]; then window="$PROMOTION_WAIT_MINUTES"; pause=120
else window="$FAILURE_RETRY_MINUTES"; pause=300; fi
find "$REQUEST_DIR" -maxdepth 1 -type f -name '*.json' -mmin "+$window" -delete
# The path unit re-triggers while requests remain; this pause is the retry backoff.
remaining=("$REQUEST_DIR"/*.json)
((${#remaining[@]} == 0)) || sleep "$pause"
exit "$status"
